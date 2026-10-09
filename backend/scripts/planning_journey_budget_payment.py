"""The same real Expense remains the sole payment fact across planning consumers."""

from datetime import date, timedelta

from scripts.planning_journey_android import wait_for
from scripts.planning_journey_budget import PAGES, SERIES


def reservation(j, amount):
    j.goto(PAGES["arrangement"])
    value = j.page.locator(".plan-breakdown > span").filter(has=j.page.get_by_text("待履约预留", exact=True)).locator("strong")
    assert f"{amount:.2f}" in value.inner_text(), "The actual arrangement reports the wrong reservation"
    j.capture(f"reservation-{amount}")


def record_payment(j, path, payment_date):
    page = j.page
    j.goto(path)
    page.get_by_role("link", name="记录本期付款", exact=True).click()
    form = j.form("/web/expenses/new")
    form.locator('[name="amount_major"]').fill("1400.00")
    form.locator('[name="merchant"]').fill(SERIES)
    if not form.locator('[name="time_precision"]').is_visible():
        form.locator("[data-manual-time] > summary").click()
    form.locator('[name="time_precision"]').select_option("date_only")
    form.locator('[name="user_local_date"]').fill(payment_date)
    accounting = form.locator('[name="accounting_date"]')
    if not accounting.is_visible():
        accounting.locator("xpath=ancestor::details[1]").locator(":scope > summary").click()
    accounting.fill(payment_date)
    assert j.facts()["expenses"] == 0, "Entering payment details created a financial fact before submission"
    form.get_by_role("button", name="记下这笔支出", exact=True).click()
    j.expect_fact("expenses", 1)
    # Manual entry confirms the explicitly submitted payment; imported suggestions use pending review.
    j.expect_fact("expense_status", "confirmed")
    assert j.facts()["expense_date"] == payment_date and j.facts()["linked_expense_id"] is None
    page.get_by_role("link", name="返回本期固定支出", exact=True).click()
    page.wait_for_url("**/occurrence?*")
    j.capture("confirmed-payment-awaiting-explicit-link")


def native_link(j, payment_date):
    native = j.native
    native.restart()
    j.open_native("series")
    native.click("查看本期")
    native.reveal_any("本期尚未履约")
    native.reveal_any("付款账期 · 留空查看全部缓存")
    native.fill(payment_date[:7], previous=j.month, label="付款账期 · 留空查看全部缓存")
    native.reveal_any(payment_date)
    matches = [node.attrib["text"] for node in native.tree().iter("node")
               if node.attrib.get("text", "").startswith(payment_date + " · " + SERIES)]
    assert len(matches) == 1, "The actual native payment picker did not offer the prior-month payment"
    native.click(matches[0])
    native.reveal_any("保存本期提交", toward_start=True)
    native.click("保存本期提交")
    j.expect_fact("linked_expense_id", j.facts()["expense_id"])
    native.reveal_any("本期已履约", toward_start=True)
    native.capture("cross-month-payment-linked")
    native.back()


def reverse_payment(j, path, payment_date):
    j.goto(path)
    assert "本期已关联付款" in j.page.inner_text("main")
    j.page.get_by_role("link", name="查看原账单", exact=True).click()
    j.page.get_by_text("退款与冲销", exact=True).click()
    j.page.get_by_role("link", name="冲销这笔账单", exact=True).click()
    panel = j.page.locator("#offset-create-reversal")
    panel.locator('[name="accounting_date"]').fill(payment_date)
    panel.locator('[name="reason"]').fill("联动验证：冲销原付款")
    panel.locator("[data-command-review]").check()
    panel.get_by_role("button", name="确认冲销", exact=True).click()
    j.expect_fact("offsets", 1)
    assert j.facts()["expenses"] == 1 and j.facts()["expense_amount"] == 140000
    j.goto(path)
    assert "付款需要重新核对" in j.page.inner_text("main")
    assert "原账单已冲销，暂不能作为本期付款依据。" in j.page.inner_text("main")
    j.capture("occurrence-needs-review-after-reversal")
    j.native.restart()
    j.open_native("series")
    j.native.click("查看本期")
    j.native.reveal_any("原付款需要重新核对")
    j.native.reveal_any("原账单已冲销，暂不能作为本期付款依据。")
    j.native.capture("occurrence-needs-review-after-reversal")
    j.native.back()


def payment_chain(j):
    path = f"/web/recurring/{j.facts()['series_id']}/occurrence"
    payment_date = (date.fromisoformat(j.month + "-01") - timedelta(days=1)).isoformat()
    reservation(j, 1400)
    record_payment(j, path, payment_date)
    native_link(j, payment_date)
    wait_for(lambda: j.facts()["occurrence_revisions"] == 1, "The explicit association did not retain one revision")
    assert j.facts()["obligation_month"] == j.month and j.facts()["expenses"] == 1
    reservation(j, 0)
    reverse_payment(j, path, payment_date)
    reservation(j, 1400)
