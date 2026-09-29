"""Use the actual shared-ledger member and viewer sessions for this planning group."""

from contextlib import closing

from scripts.planning_journey_budget import PAGES
from scripts.planning_journey_roles import _member_code


def connect(j, page, role):
    base = j.base_url.replace("127.0.0.1", "localhost")
    code = _member_code(j.ledger_id, role)
    page.goto(base + "/web/auth/login?next=/web/budgets")
    page.locator('[name="pairing_code"]').fill(code)
    page.locator('form[action="/web/auth/login"] button[type="submit"]').click()
    page.wait_for_url("**/web/budgets*")
    return base


def member(j, page, base):
    for path, action, family, field, amount, fact in (
        (PAGES["budget"], "/web/budgets/save", "budget", "total_amount_yuan", "11500.00", "budget_amount"),
        (PAGES["arrangement"], "/web/budget-advise", "arrangement", "savings_target_yuan", "1150.00", "savings"),
        (PAGES["series"], f"/web/recurring/{j.facts()['series_id']}/edit", "recurring", "baseline_amount_yuan", "1450.00", "series_amount"),
    ):
        page.goto(f"{base}{path}?ledger_id={j.ledger_id}&month={j.month}")
        form = j.form(action, page=page)
        form.locator(f'[name="{field}"]').fill(amount)
        form.locator(f"[data-{family}-submit]").click()
        j.expect_fact(fact, int(amount.replace(".", "")))
        j.capture("member-" + family, page=page)


def viewer(j, page, base):
    for kind, path in PAGES.items():
        page.goto(f"{base}{path}?ledger_id={j.ledger_id}&month={j.month}")
        writes = page.locator("[data-budget-submit], [data-arrangement-submit], [data-recurring-submit], form[action='/web/budgets/archive'] button")
        assert all(not button.is_enabled() for button in writes.all()), "The viewer has an enabled write control"
        assert page.locator('form[action$="/edit"]').count() == 0
        j.capture("viewer-" + kind, page=page)
        history = f"/web/recurring/{j.facts()['series_id']}/history" if kind == "series" else path + "/history"
        page.locator(f'a[href^="{history}?"]').click()
        original = {"budget": "10000.00", "arrangement": "1000.00", "series": "1200.00"}[kind]
        assert original in page.inner_text("main").replace(",", ""), "The viewer did not read the original definition"
        j.capture("viewer-" + kind + "-history", page=page)


def roles(j):
    with closing(j.page.context.browser.new_context()) as context:
        page = context.new_page()
        member(j, page, connect(j, page, "member"))
    with closing(j.page.context.browser.new_context()) as context:
        page = context.new_page()
        viewer(j, page, connect(j, page, "viewer"))
    j.native.restart()
    for kind, values in (("budget", ("11,500", "11500")), ("arrangement", ("1,150", "1150")),
                         ("series", ("1,450", "1450"))):
        j.open_native(kind)
        j.native.reveal_any(*values)
        j.native.capture("owner-" + kind + "-after-member-edit")
