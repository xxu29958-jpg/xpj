"""Interrupt and resume original planning submissions and existing recycle commands."""

from scripts.planning_journey_android import wait_for
from scripts.planning_journey_budget import PAGES, SERIES
from scripts.planning_journey_recovery import assert_original


class BudgetRecovery:
    def __init__(self, journey):
        self.j = journey
        self.page, self.native = journey.page, journey.native

    def arrangement_original(self):
        j, native = self.j, self.native
        j.goto(PAGES["arrangement"])
        form = j.form("/web/budget-advise")
        form.locator('[name="savings_target_yuan"]').fill("1250.00")
        original = {name: form.locator(f'[name="{name}"]').input_value()
                    for name in ("idempotency_key", "expected_row_version", "savings_target_yuan")}
        j.open_native("arrangement")
        native.reveal_any("1000", "1,000")
        native.fill("1100.00", previous=r"1,?000(?:\.00)?")
        native.fill("600.00", previous=r"500(?:\.00)?")
        native.click("试算，不保存")
        native.reveal_any("本次试算：尚未保存")
        assert j.facts()["arrangement_revisions"] == 1, "Native trial saved a definition"
        native.connection(j.port, online=False)
        native.click("明确保存本月安排")
        native.reveal_any("原安排提交已保留", "等待确认")
        native.restart()
        j.open_native("arrangement")
        native.reveal_any("等待确认")
        native.capture("arrangement-original-after-offline-restart")
        assert j.facts()["savings"] == 100000
        native.connection(j.port, online=True)
        # The actual outbox resumes its retained command automatically after reconnection.
        j.expect_fact("savings", 110000)
        assert j.facts()["buffer"] == 60000 and j.facts()["arrangement_revisions"] == 2
        native.reveal_any("服务器已确认原提交")
        native.capture("arrangement-original-confirmed-after-reconnect")
        self.reject_stale(form, original)

    def reject_stale(self, form, original):
        j, page = self.j, self.page
        before = j.facts()
        with page.expect_response(lambda response: response.url.endswith("/web/budget-advise/save")
                and response.request.method == "POST") as response:
            form.locator("[data-arrangement-submit]").click()
        assert response.value.status == 409, "A stale arrangement overwrote the native change"
        page.wait_for_function("document.querySelector('[data-arrangement-draft-phase]').dataset.arrangementDraftPhase === 'blocked'")
        page.reload()
        assert_original(form, original)
        assert "服务器已拒绝" in form.locator("[data-arrangement-draft-status]").inner_text()
        assert j.facts() == before, "Rejecting an old arrangement changed the stored definition"
        j.capture("arrangement-retained-stale-original")
        page.on("dialog", lambda dialog: dialog.accept())
        form.locator("[data-arrangement-discard]").click()

    def series_reply_loss(self):
        j, page = self.j, self.page
        path = f"/web/recurring/{j.facts()['series_id']}/edit"
        j.goto(PAGES["series"])
        form = j.form(path)
        form.locator('[name="baseline_amount_yuan"]').fill("1400.00")
        original = {name: form.locator(f'[name="{name}"]').input_value()
                    for name in ("idempotency_key", "expected_row_version", "baseline_amount_yuan")}
        delivered = []

        def lose_reply(route):
            if route.request.method != "POST":
                route.continue_()
                return
            response = route.fetch(max_redirects=0)
            assert response.status == 200, "The real series edit was not accepted before reply loss"
            delivered.append(response.json()["receipt"]["public_id"])
            route.abort("connectionclosed")

        page.route("**" + path, lose_reply)
        form.locator("[data-recurring-submit]").click()
        page.get_by_text("暂未收到保存回执。", exact=False).wait_for()
        assert delivered == [j.facts()["series_id"]]
        before = j.facts()["series_revisions"]
        page.unroute("**" + path, lose_reply)
        page.reload()
        form = j.form(path)
        assert_original(form, original)
        j.capture("series-lost-reply-original")
        form.locator("[data-recurring-submit]").click()
        page.wait_for_url("**/web/recurring?*")
        assert j.facts()["series_revisions"] == before, "Replay created a second series edit"

    def web_archive(self, kind):
        j = self.j
        j.goto(PAGES[kind])
        action = "/web/budgets/archive" if kind == "budget" else f"/web/recurring/{j.facts()['series_id']}/archive"
        j.form(action).locator('button[type="submit"]').click()
        self.page.locator("#tb-confirm-modal[open]").get_by_role("button", name="确认", exact=True).click()
        j.expect_fact("budget_archived" if kind == "budget" else "series_status", True if kind == "budget" else "archived")

    def web_restore(self, kind):
        j = self.j
        key = "monthly_budget:" + j.month if kind == "budget" else "recurring_item:" + j.facts()["series_id"]
        j.goto("/web/recycle-bin")
        self.page.locator(f'[data-restore-key="{key}"] form button[type="submit"]').click()
        self.page.locator("#tb-confirm-modal[open]").get_by_role("button", name="确认", exact=True).click()
        j.expect_fact("budget_archived" if kind == "budget" else "series_status", False if kind == "budget" else "active")

    def native_restore(self, kind):
        self.native.recycle_bin()
        anchor = self.j.month + " 月度预算" if kind == "budget" else SERIES
        self.native.reveal_any(anchor)
        self.native.click_within(anchor, "恢复")
        wait_for(lambda: self.native.has("恢复项目？"), "The existing recycle confirmation did not open")
        self.native.click("恢复", bottom=True)
        self.j.expect_fact("budget_archived" if kind == "budget" else "series_status", False if kind == "budget" else "active")

    def lifecycle(self):
        j, native = self.j, self.native
        j.open_native("series")
        native.click("暂停固定支出")
        j.expect_fact("series_status", "paused")
        native.click_counted_tab("暂停")
        native.click("继续固定支出")
        j.expect_fact("series_status", "active")
        self.web_archive("series")
        j.open_native("series")
        native.click_counted_tab("已归档")
        native.click("恢复固定支出")
        j.expect_fact("series_status", "active")
        self.web_archive("series")
        self.native_restore("series")
        j.open_native("series")
        native.click("归档固定支出")
        j.expect_fact("series_status", "archived")
        self.web_restore("series")
        self.web_archive("budget")
        self.native_restore("budget")
        j.open_native("budget")
        native.click("将本月预算移入回收站")
        native.click("移入回收站")
        j.expect_fact("budget_archived", True)
        self.web_restore("budget")
        assert j.facts()["expenses"] == 0, "A planning lifecycle action created a payment"

    def run(self):
        self.arrangement_original()
        self.series_reply_loss()
        self.lifecycle()
        self.native.restart()
        self.j.history()
        self.native.connection(self.j.port, online=False)
        self.native.restart()
        self.j.history(offline=True)
        self.native.connection(self.j.port, online=True)
