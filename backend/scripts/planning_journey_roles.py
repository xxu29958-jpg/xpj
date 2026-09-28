"""Exercise existing member/viewer consumers in the same isolated ledger."""

from __future__ import annotations

from contextlib import closing

from scripts.planning_journey_android import wait_for
from scripts.planning_journey_recovery import open_web_editor


def _member_code(ledger_id, role):
    from app.database import SessionLocal
    from app.models import Account, LedgerMember
    from app.services.identity_service import create_pairing_code

    with SessionLocal() as db:
        account = Account(display_name=f"联动验证 {role}")
        db.add(account)
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role=role))
        db.flush()
        # Only fixture identity is seeded; product commands still use the real UI.
        return create_pairing_code(db, ledger_id=ledger_id, account_id=account.id, ttl_minutes=60).pairing_code


def _connect(page, base_url, ledger_id, role):
    code = _member_code(ledger_id, role)
    page.goto(f"{base_url}/web/auth/login?next=/web/income-plans")
    page.locator('[name="pairing_code"]').fill(code)
    page.locator('form[action="/web/auth/login"] button[type="submit"]').click()
    page.wait_for_url("**/web/income-plans*")
    assert "联动工资" in page.inner_text("main"), "The member did not reach the shared ledger"


def _edit(page, base_url, ledger_id, path, field, value):
    form = open_web_editor(page, base_url, ledger_id, path)
    form.locator(f'[name="{field}"]').fill(value)
    form.locator('button[type="submit"]:not([name])').click()
    family = path.split("/")[2]
    page.wait_for_url(f"{base_url}/web/{family}?*")


def verify_roles(page, native, fixture, evidence, facts, base_url):
    ledger_id = fixture.ledger_id
    current = facts(ledger_id)
    with closing(page.context.browser.new_context()) as context:
        member = context.new_page()
        _connect(member, base_url, ledger_id, "member")
        _edit(member, base_url, ledger_id, f"/web/income-plans/{current['income_id']}/edit", "amount_yuan", "6300.00")
        wait_for(lambda: facts(ledger_id)["income_amount"] == 630000, "The actual member income edit did not commit")
        _edit(member, base_url, ledger_id, f"/web/goals/{current['goal_id']}/edit", "target_amount_yuan", "2500.00")
        wait_for(lambda: facts(ledger_id)["goal_amount"] == 250000, "The actual member goal edit did not commit")
        member.screenshot(path=evidence / "web-member-shared-goal.png", full_page=True)
    with closing(page.context.browser.new_context()) as context:
        viewer = context.new_page()
        _connect(viewer, base_url, ledger_id, "viewer")
        assert "只读角色" in viewer.inner_text("main")
        for family, resource in (("income-plans", current["income_id"]), ("goals", current["goal_id"])):
            viewer.goto(f"{base_url}/web/{family}?ledger_id={ledger_id}")
            assert viewer.locator(f'a[href*="/{resource}/edit"]').count() == 0
            buttons = viewer.locator(f'form[action="/web/{family}/create"] button[type="submit"]:not([name])')
            for button in buttons.all():
                assert button.is_disabled(), "The viewer has an enabled write control"
            viewer.screenshot(path=evidence / f"web-viewer-{family}.png", full_page=True)
            viewer.goto(f"{base_url}/web/{family}/{resource}/history?ledger_id={ledger_id}")
            assert "5000.00" in viewer.inner_text("main") if family == "income-plans" else "2000.00" in viewer.inner_text("main")
            viewer.screenshot(path=evidence / f"web-viewer-{family}-history.png", full_page=True)
    native.restart()
    native.open_income()
    wait_for(lambda: native.has("6,300") or native.has("6300"), "The owner native income did not read the member's change")
    native.capture("owner-income-after-member-edit")
    native.open_goal()
    wait_for(lambda: native.has("2,500") or native.has("2500"), "The owner native goal did not read the member's change")
    native.capture("owner-goal-after-member-edit")
