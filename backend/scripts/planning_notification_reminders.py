"""Actual fresh-source reminders, OS channel recovery and return to original input."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.planning_journey_android import wait_for

CHANNELS = ("ticketbox.recurring", "ticketbox.budget", "ticketbox.backup")
SERIES = "通知验证固定支出"


class NotificationReminders:
    def __init__(self, journey):
        self.j = journey
        self.native = journey.native

    def facts(self):
        from sqlalchemy import select

        from app.database import SessionLocal
        from app.models import Budget, Expense, RecurringItem, RecurringOccurrence

        with SessionLocal() as db:
            ledger = self.j.fixture.ledger_id
            budget = db.scalar(select(Budget).where(Budget.tenant_id == ledger))
            series = db.scalar(select(RecurringItem).where(RecurringItem.tenant_id == ledger))
            return {"budget": budget.total_amount_cents if budget else None,
                "series": series.public_id if series else None,
                "expected_date": str(series.next_expected_date) if series else None,
                "expenses": [{"id": item.id, "status": item.status, "amount": item.amount_cents} for item in
                    db.scalars(select(Expense).where(Expense.tenant_id == ledger))],
                "occurrences": len(list(db.scalars(select(RecurringOccurrence).where(RecurringOccurrence.tenant_id == ledger))))}

    def create_plan_inputs(self):
        page = self.j.page
        self.j.goto("/web/budgets")
        form = page.locator('form[action="/web/budgets/save"]')
        if not form.is_visible():
            form.locator("xpath=ancestor::details").locator("summary").click()
        self.month = form.locator('[name="month"]').input_value()
        form.locator('[name="total_amount_yuan"]').fill("10.00")
        form.locator('[data-budget-submit]').click()
        wait_for(lambda: self.facts()["budget"] == 1000, "The actual Web budget was not accepted")
        self.j.goto("/web/recurring")
        form = page.locator('form[action="/web/recurring/create"]')
        if not form.is_visible():
            form.locator("xpath=ancestor::details").locator("summary").click()
        form.locator('[name="merchant"]').fill(SERIES)
        form.locator('[name="baseline_amount_yuan"]').fill("20.00")
        self.expected_date = self.native.adb("shell", "date", "+%F").strip()
        form.locator('[name="next_expected_date"]').fill(self.expected_date)
        form.locator('[data-recurring-submit]').click()
        wait_for(lambda: self.facts()["series"], "The actual Web fixed expense was not accepted")

    def set_channel(self, channel, enabled):
        native = self.native
        native.adb("shell", "am", "start", "-a", "android.settings.CHANNEL_NOTIFICATION_SETTINGS",
            "--es", "android.provider.extra.APP_PACKAGE", "com.ticketbox", "--es", "android.provider.extra.CHANNEL_ID", channel)

        def control():
            switches = [node for node in native.tree().iter("node") if node.attrib.get("package") == "com.android.settings" and
                node.attrib.get("checkable") == "true" and "Switch" in node.attrib.get("class", "")]
            return [min(switches, key=lambda node: native.bounds(node)[1])] if switches else []

        switch = wait_for(control, "The Android channel page did not expose its master control")[0]
        expected = str(enabled).lower()
        if switch.attrib.get("checked") != expected:
            native.tap(switch)
        wait_for(lambda: bool(nodes := control()) and nodes[0].attrib.get("checked") == expected,
            "The Android notification channel did not change")
        native.capture(f"notification-channel-{channel.rsplit('.', 1)[1]}-{expected}")
        native.back()

    def run_existing_checks(self, stage):
        test_apk = Path("../android/app/build/outputs/apk/androidTest/gray/debug/app-gray-debug-androidTest.apk").resolve()
        assert test_apk.is_file()
        if stage == "blocked":
            self.native.adb("install", "-r", str(test_apk))
        result = subprocess.run(["adb", "-s", self.native.serial, "shell", "am", "instrument", "-w",
            "-e", "class", "com.ticketbox.ui.navigation.NotificationJourneyRuntimeTest",
            "-e", "ticketboxNotificationJourney", "isolated-cloud", "-e", "channels", stage,
            "com.ticketbox.test/androidx.test.runner.AndroidJUnitRunner"],
            capture_output=True, text=True, timeout=120, check=False)
        (self.j.evidence / f"notification-runtime-{stage}.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
        assert result.returncode == 0 and "OK (1 test)" in result.stdout, "Fresh-source checks failed; see the retained actual runtime result"

    def configure_and_confirm(self):
        for channel in CHANNELS:
            self.set_channel(channel, False)
        self.native.plan_home()
        self.native.click("打开账户与设置")
        self.native.click("通知与提醒")
        for label in ("固定支出提醒", "预算超支提醒", "备份超龄提醒"):
            self.native.set_switch(label, True)
        assert self.facts()["expenses"][0]["status"] == "pending"
        self.j.tap_notification("16.80", expected="确认账单")
        self.native.capture("notification-expense-original")
        self.native.click("确认入账")
        wait_for(lambda: self.facts()["expenses"][0]["status"] == "confirmed", "The captured payment did not wait for actual human confirmation")
        assert self.facts()["expenses"][0]["amount"] == 1680
        self.run_existing_checks("blocked")
        for channel in CHANNELS:
            self.set_channel(channel, True)
        self.run_existing_checks("enabled")

    def original_taps(self):
        from scripts.planning_notification_context import share_original, shared_original_result

        self.j.tap_notification("本月预算超了", expected="月度总预算")
        self.native.fill("321.09", label="月度总预算")
        self.native.capture("notification-budget-original-input")
        self.j.tap_notification("备份记录太久没更新", expected="备份")
        self.native.reveal_any("尚未发现备份发布记录")
        self.native.capture("notification-backup-original-server")
        for _ in range(3):
            self.native.back()
            if self.native.has("321.09"):
                break
        self.native.reveal_any("321.09")
        self.native.capture("notification-back-to-original-budget-input")
        assert self.facts()["budget"] == 1000, "Opening another reminder silently submitted the user's budget input"
        self.native.connection(self.j.port, online=False)
        digest = share_original(self.j)
        self.j.tap_notification(SERIES, expected="固定支出")
        # A fresh active-only reminder query is not a previously read full list
        # or occurrence. Keep the original target through its first offline read.
        self.native.reveal_any("固定支出暂时打不开")
        self.native.capture("notification-fixed-first-read-offline")
        self.native.connection(self.j.port, online=True)
        self.native.click("重试")
        self.native.reveal_any(SERIES)
        self.native.reveal_any(self.expected_date)
        self.native.capture("notification-original-fixed-occurrence")
        reminder_facts = self.facts()
        assert reminder_facts["expected_date"] == self.expected_date, "Opening a reminder advanced the fixed-expense due date"
        assert len(reminder_facts["expenses"]) == 1, f"Opening a reminder changed the expected bill count: {reminder_facts['expenses']}"
        self.native.connection(self.j.port, online=False)
        self.native.back()
        self.native.reveal_any("添加固定支出")
        self.native.back()
        self.native.reveal_any("重试上传")
        self.j.background_process_death()
        self.j.reopen_original_task()
        self.native.reveal_any("重试上传")
        self.native.capture("notification-return-to-original-share")
        self.native.connection(self.j.port, online=True)
        self.native.click("重试上传")
        self.shared_original = wait_for(lambda: shared_original_result(self.j, digest),
            "The saved image did not continue after returning from its reminder", 120)

    def run(self):
        self.create_plan_inputs()
        self.configure_and_confirm()
        self.original_taps()
        return {**self.facts(), "shared_original": self.shared_original}
