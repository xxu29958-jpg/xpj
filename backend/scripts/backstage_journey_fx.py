"""Actual dated quote failure/retry, original currency and explicit two-client review."""

from decimal import ROUND_HALF_UP, Decimal

from scripts.backstage_journey_facts import denied_membership
from scripts.backstage_journey_native import open_latest_source
from scripts.planning_journey_android import wait_for


def _expense(j):
    return j.facts()["expenses"][-1]


def _task(j):
    tasks = [task for task in j.facts()["tasks"] if task["type"] == "expense_fx"]
    return tasks[-1] if tasks else None


def _load_latest(j):
    j.native.reveal_any("加载最新账单")
    j.native.click("加载最新账单")
    if j.native.has("替换并载入"):
        j.native.click("替换并载入")
    j.native.reveal_any("23.45", toward_start=True)


def fx_consumers(j):
    open_latest_source(j)
    j.native.reveal_any("¥ CNY", toward_start=True)
    j.native.click("¥ CNY")
    j.native.click("USD")
    j.native.click("保存")
    wait_for(lambda: _expense(j)["original_currency"] == "USD", "The actual native currency edit did not save", 90)
    wait_for(lambda: _task(j) and _task(j)["status"] == "failed", "The quote outage did not leave a resumable FX result", 90)
    wait_for(lambda: j.native.has("原操作已完成"), "The native currency command has not completed")
    _load_latest(j)
    j.native.reveal_any("换算未完成")
    j.native.capture("backstage-fx-outage")
    original = _expense(j)
    assert original["original_amount"] == 2345 and original["status"] == "pending"
    assert original["fx_status"] == "pending" and original["expense_time"].startswith("2025-01-12")
    j.goto(f'/web/expenses/{original["id"]}/edit')
    form = j.page.locator(f'form[action="/web/expenses/{original["id"]}/save"]')
    version = form.locator('[name="expected_row_version"]').input_value()
    form.locator('[name="amount_yuan"]').fill("29.00")
    form.locator('[name="note"]').fill("换算完成前的原输入")
    j.native.fill("27.00", previous=r"23\.45")
    j.advisor.fx_available = True
    j.native.reveal_any("重新换算")
    j.native.click("重新换算")
    wait_for(lambda: _task(j)["status"] == "completed", "Real historical FX did not recover", 180)
    updated = _expense(j)
    assert updated["fx_status"] == "ready" and updated["status"] == "pending"
    assert updated["original_currency"] == "USD" and updated["original_amount"] == 2345
    assert updated["home_currency"] == "CNY" and updated["rate_date"] == "2025-01-10"
    assert updated["expense_time"].startswith("2025-01-12"), "Publication date replaced the transaction date"
    assert updated["amount"] == int((Decimal(2345) * Decimal(updated["rate"])).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    assert updated["original_sha256"] == original["original_sha256"]
    form.get_by_role("button", name="刷新汇率状态", exact=True).click()
    assert form.locator('[name="expected_row_version"]').input_value() == version
    assert form.locator('[name="amount_yuan"]').input_value() == "29.00"
    assert form.locator('[name="note"]').input_value() == "换算完成前的原输入"
    assert "已保存账单有新结果" in j.page.inner_text("main")
    j.capture("fx-web-keeps-input-and-version")
    j.native.reveal_any("刷新换算状态")
    j.native.click("刷新换算状态")
    wait_for(lambda: j.native.has("换算任务已完成"), "Native did not read the completed original FX task")
    j.native.reveal_any("27.00", toward_start=True)
    j.native.capture("backstage-fx-native-keeps-input")
    with denied_membership(j.ledger_id):
        j.native.reveal_any("刷新换算状态")
        j.native.click("刷新换算状态")
        wait_for(lambda: not j.native.has("换算任务已完成"), "Revoked FX read still exposes its old task result")
        j.native.reveal_any("27.00", toward_start=True)
        j.native.capture("backstage-fx-read-refused-input-retained")
    j.native.reveal_any("刷新换算状态")
    j.native.click("刷新换算状态")
    wait_for(lambda: j.native.has("换算任务已完成"), "Native FX did not recover on the same identity")
    _load_latest(j)
    j.native.capture("backstage-fx-explicit-current-review")
    assert _expense(j) == updated, "Read recovery or explicit review wrote financial facts"
    j.page.get_by_role("link", name="载入最新账单（替换未保存填写）", exact=True).click()
    assert j.page.locator('[name="amount_yuan"]').input_value() == "23.45"
    j.capture("fx-web-explicit-current-review")
