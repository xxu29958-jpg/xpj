"""Real payment sources, Android notification access and original Web/native tasks."""

from __future__ import annotations

import json

from scripts.planning_journey_android import wait_for
from scripts.planning_notification_reminders import NotificationReminders
from scripts.planning_notification_source import SystemPaymentSources, notification_control


class NotificationJourney:
    def __init__(self, page, native, fixture, evidence, base_url):
        self.page, self.native, self.fixture = page, native, fixture
        self.evidence, self.base_url, self.port = evidence, base_url, 18880

    def facts(self):
        from sqlalchemy import select

        from app.database import SessionLocal
        from app.models import Debt, Expense, Repayment, RepaymentDraft

        with SessionLocal() as db:
            drafts = list(db.scalars(select(RepaymentDraft).where(RepaymentDraft.tenant_id == self.fixture.ledger_id)))
            debts = list(db.scalars(select(Debt).where(Debt.tenant_id == self.fixture.ledger_id)))
            payments = list(db.scalars(select(Repayment).where(Repayment.debt_id.in_([debt.id for debt in debts]))))
            return {"captures": [{"id": item.public_id, "status": item.status, "original": item.original_amount_minor,
                        "repayment": item.committed_repayment_public_id} for item in drafts],
                    "debts": [{"id": debt.public_id, "version": debt.row_version} for debt in debts],
                    "payments": [{"id": item.public_id, "amount": item.amount_cents} for item in payments],
                    "expenses": len(list(db.scalars(select(Expense).where(Expense.tenant_id == self.fixture.ledger_id))))}

    def goto(self, path):
        self.page.goto(self.base_url + path + ("&" if "?" in path else "?") + "ledger_id=" + self.fixture.ledger_id)

    def capture(self, name):
        assert not self.page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Review overflows the actual Web viewport"
        self.page.screenshot(path=self.evidence / f"web-notification-{name}.png", full_page=True)

    def prepare(self):
        self.page.goto(self.base_url + "/web/auth/local?next=/web/repayment-drafts")
        self.page.locator(f'input[name="ledger_id"][value="{self.fixture.ledger_id}"]').check()
        self.page.locator('form[action="/web/auth/local"] button[type="submit"]').click()
        self.page.wait_for_url("**/web/repayment-drafts*")
        self.goto("/web/debts/new")
        form = self.page.locator('form[action="/web/debts"]')
        form.locator('[name="counterparty_label"]').fill("采集核对欠款")
        form.locator('[name="amount_major"]').fill("400.00")
        form.get_by_role("button", name="记下这笔欠款", exact=True).click()
        wait_for(lambda: len(self.facts()["debts"]) == 1, "Web did not create the review target")
        self.native.bind(self.fixture.pairing_code, self.port)
        self.native.plan_home()
        self.native.click("打开账户与设置")
        self.native.click("通知与提醒")
        self.native.set_switch("待确认提醒", True)
        self.native.capture("notification-configured")
        self.sources = SystemPaymentSources(self.native, self.evidence.parent / "notification-input-apks")
        self.sources.capture_payments(self.facts)
        wait_for(lambda: len(self.facts()["captures"]) == 2 and self.facts()["expenses"] == 1,
            "Controlled notifications did not reach their correct original owners")
        assert self.facts()["payments"] == [], "Capture must not automatically record repayment"
        self.background_process_death()

    def tap_notification(self, amount, expected="还款采集"):
        def show_shade():
            self.native.adb("shell", "cmd", "statusbar", "expand-notifications")
            return any(node.attrib.get("resource-id") == "com.android.systemui:id/notification_stack_scroller"
                for node in self.native.tree().iter("node"))

        wait_for(show_shade, "Android did not display the actual notification shade")
        self.native.capture(f"notification-shade-{amount}")
        self.native.reveal_any(amount)
        self.native.capture(f"notification-tap-{amount}")
        action, control = notification_control(self.native.tree(), amount)
        if action == "expand":
            self.native.tap(control)
            self.native.reveal_any(amount)
            self.native.capture(f"notification-expanded-{amount}")
            action, control = notification_control(self.native.tree(), amount)
        assert action == "open", "The actual individual reminder is still collapsed"
        self.native.tap(control)
        self.native.reveal_any(expected)

    def background_process_death(self):
        self.native.adb("shell", "input", "keyevent", "3")
        wait_for(lambda: any(node.attrib.get("package") == "com.google.android.apps.nexuslauncher"
            for node in self.native.tree().iter("node")), "Android did not move the original task into the background")

        def state_saved():
            dump = self.native.adb("shell", "dumpsys", "activity", "-a", "-p", "com.ticketbox", "activities")
            lines = [line.strip() for line in dump.splitlines()]
            states = [line.split()[0] for line in lines if line.startswith("state=")]
            bundles = [line for line in lines if line.startswith("mHaveState=")]
            snapshot = {"activity_records": len(bundles), "stopped": states == ["state=STOPPED"],
                "saved_bundle": len(bundles) == 1 and "mHaveState=true" in bundles[0] and "mIcicle=null" not in bundles[0]}
            # Persist only lifecycle flags, never the framework Bundle or Intent contents.
            (self.evidence / f"notification-background-{self.native.tree_attempt}.json").write_text(json.dumps(snapshot), encoding="utf-8")
            return snapshot["stopped"] and snapshot["saved_bundle"]

        wait_for(state_saved, "Android did not retain the stopped original Activity state")
        original_pid = self.native.adb("shell", "pidof", "com.ticketbox").strip()
        assert original_pid.isdigit(), "The original application process is ambiguous"
        # A live notification listener can keep the process above am-kill's OOM
        # threshold. Signal only this debuggable app's own UID after Home saves state.
        self.native.adb("shell", "run-as", "com.ticketbox", "kill", "-9", original_pid)
        wait_for(lambda: not any(line.split()[-1:] == ["com.ticketbox"] and line.split()[1] == original_pid
            for line in self.native.adb("shell", "ps", "-A").splitlines()), "The original process did not stop")

    def reopen_original_task(self):
        result = self.native.adb("shell", "am", "start", "-W", "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER", "-n", "com.ticketbox/.MainActivity")
        (self.evidence / f"notification-launcher-return-{self.native.tree_attempt}.txt").write_text(result, encoding="utf-8")
        assert "Status: ok" in result, "Android did not reopen the original launcher task"

    def native_original(self):
        self.tap_notification("100.00")
        self.native.click_within("花呗", "核对并处理")
        self.native.reveal_any("核对这笔还款")
        self.native.fill("90.00", label="核对金额")
        self.native.click("选择要偿还的欠款")
        self.native.click("采集核对欠款")
        self.native.capture("notification-native-unsubmitted")
        # A second system PendingIntent is opened while the first editor exists.
        self.tap_notification("80.00")
        self.native.click_within("白条", "核对并处理")
        self.native.reveal_any("核对这笔还款")
        self.native.capture("notification-second-original")
        self.native.back()
        self.native.back()
        self.native.reveal_any("90.00")
        self.native.connection(self.port, online=False)
        self.native.click("确认记还款")
        self.native.reveal_any("原提交")
        assert self.facts()["payments"] == []
        self.native.capture("notification-offline-original")
        self.background_process_death()
        self.reopen_original_task()
        self.native.reveal_any("核对这笔还款")
        self.native.reveal_any("90.00")
        self.native.capture("notification-process-restored")
        self.native.connection(self.port, online=True)
        wait_for(lambda: len(self.facts()["payments"]) == 1, "The saved original did not resume after connectivity returned", 120)
        assert self.facts()["payments"][0]["amount"] == 9000

    def web_original(self):
        pending = next(item for item in self.facts()["captures"] if item["status"] == "pending")
        self.goto("/web/repayment-drafts/" + pending["id"])
        action = f"/web/repayment-drafts/{pending['id']}/review"
        form = self.page.locator(f'form[action="{action}"]')
        form.locator('[name="original_amount"]').fill("70.00")
        choice = form.locator('[name="target_with_expected_row_version"] option').nth(1).get_attribute("value")
        form.locator('[name="target_with_expected_row_version"]').select_option(choice)
        key = form.locator('[name="idempotency_key"]').input_value()
        self.page.reload()
        form.locator('[name="original_amount"]').wait_for()
        wait_for(lambda: form.locator('[name="idempotency_key"]').input_value() == key, "The browser did not restore the original key")
        assert form.locator('[name="original_amount"]').input_value() == "70.00"
        self.capture("unsubmitted-restored")

        def lose_reply(route):
            response = route.fetch()
            assert response.status == 200
            route.abort("connectionclosed")

        self.page.route("**" + action, lose_reply, times=1)
        form.locator('[data-repayment-submit]').click(no_wait_after=True)
        wait_for(lambda: len(self.facts()["payments"]) == 2, "Web review did not reach the shared repayment owner")
        self.goto("/web/repayment-drafts/" + pending["id"])
        wait_for(lambda: form.locator('[name="idempotency_key"]').input_value() == key, "The unresolved original disappeared after response loss")
        assert form.locator('[name="target_with_expected_row_version"]').input_value() == choice
        assert form.locator('[name="original_amount"]').input_value() == "70.00"
        form.locator('[data-repayment-submit]').click()
        self.page.locator('[data-repayment-ack]').wait_for()
        assert sorted(item["amount"] for item in self.facts()["payments"]) == [7000, 9000]
        self.capture("original-receipt")

    def appearances(self):
        for theme in ("paper", "midnight"):
            self.goto("/web/repayment-drafts")
            self.page.locator("#appearance > summary").click()
            self.page.locator(f'#appearance [data-theme-mode="{theme}"]').click()
            self.page.wait_for_function("theme => document.documentElement.dataset.theme === theme", arg=theme)
            self.page.locator("#appearance > summary").click()
            for width in (1280, 390):
                self.page.set_viewport_size({"width": width, "height": 960})
                self.goto("/web/repayment-drafts")
                self.capture(f"history-{width}-{theme}")
                for capture in self.facts()["captures"]:
                    self.goto("/web/repayment-drafts/" + capture["id"])
                    assert "已记账" in self.page.inner_text("main")
                    self.capture(f"original-{capture['original']}-{width}-{theme}")
        for theme, label in (("paper", "晨纸"), ("midnight", "玄夜")):
            self.native.plan_home()
            self.native.click("打开账户与设置")
            self.native.click("外观与主题")
            self.native.click(label)
            self.native.plan_home()
            self.native.click("打开账户与设置")
            self.native.click("通知与提醒")
            self.native.capture("notification-preferences-" + theme)
            self.native.plan_home()
            self.native.click("往来", bottom=True)
            self.native.click("还款复核")
            self.native.click("已处理 2")
            self.native.reveal_any("花呗")
            self.native.capture("notification-native-history-" + theme)
            self.native.click_within("花呗", "查看原处理记录")
            self.native.reveal_any("90.00")
            self.native.capture("notification-native-original-" + theme)

    def run(self):
        from scripts.planning_notification_context import identity_changes

        self.prepare()
        self.native_original()
        self.web_original()
        reminders = NotificationReminders(self).run()
        self.appearances()
        identity = identity_changes(self)
        result = self.facts()
        result["reminders"] = reminders
        result["identity"] = identity
        assert sorted(item["original"] for item in result["captures"]) == [6000, 6100, 8000, 10000]
        result["verified_leg"] = "Actual Android notification-access grant and isolated source apps; application off/on and source allowlist; real native NLS/parser/Outbox/HTTP/notifier; cold and warm OS taps; native offline process restoration; Web retained edit and lost receipt; original money and one repayment per confirmation; real Expense confirmation; three fresh-source reminder channels refused then restored; original Budget/Backup/Recurring taps; retained unfinished input and original image share; actual ledger/account switches require the original identity; light/dark native history and original review plus wide/narrow Web"
        return result
