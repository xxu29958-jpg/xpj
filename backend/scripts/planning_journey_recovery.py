"""Continue the same real consumer journey through interruption and recovery."""

from __future__ import annotations

from scripts.planning_journey_android import wait_for


def open_web_editor(page, base_url, ledger_id, path):
    family = path.split("/")[2]
    page.goto(f"{base_url}/web/{family}?ledger_id={ledger_id}")
    # Follow the consumer's link, including its original month and return context.
    page.locator(f'a[href^="{path}?"]').click()
    return page.locator(f'form[action="{path}"]')


def assert_original(form, original):
    from playwright.sync_api import expect

    for name, value in original.items():
        expect(form.locator(f'[name="{name}"]')).to_have_value(value)


class PlanningRecovery:
    def __init__(self, page, native, fixture, evidence, facts, base_url):
        self.page = page
        self.native = native
        self.ledger_id = fixture.ledger_id
        self.evidence = evidence
        self.facts = lambda: facts(self.ledger_id)
        self.base_url = base_url
        self.port = int(base_url.rsplit(":", 1)[1])

    def web_lost_reply(self, kind, amount, field):
        """Deliver the real command, lose only its reply, then reopen and replay."""
        family = "income-plans" if kind == "income" else "goals"
        path = f"/web/{family}/{self.facts()[kind + '_id']}/edit"
        page = self.page
        form = open_web_editor(page, self.base_url, self.ledger_id, path)
        form.locator(f'[name="{field}"]').fill(amount)
        original = {name: form.locator(f'[name="{name}"]').input_value()
                    for name in ("idempotency_key", "expected_row_version", field)}
        delivered = []

        def lose_reply(route):
            if route.request.method != "POST":
                route.continue_()
                return
            response = route.fetch(max_redirects=0)
            assert response.status == 200, "The real command was not accepted before reply loss"
            delivered.append(response.json()["receipt"]["public_id"])
            route.abort("connectionclosed")

        page.route("**" + path, lose_reply)
        form.locator('button[type="submit"]').first.click()
        page.get_by_text("暂未收到保存回执。", exact=False).wait_for()
        assert delivered == [self.facts()[kind + "_id"]]
        revisions = self.facts()[kind + "_revisions"]
        page.unroute("**" + path, lose_reply)
        page.reload()
        assert_original(form, original)
        page.screenshot(path=self.evidence / f"web-{kind}-retained-original.png", full_page=True)
        form.locator('button[type="submit"]').first.click()
        page.wait_for_url(f"**/web/{family}?*")
        assert self.facts()[kind + "_revisions"] == revisions, "Replaying created a second revision"

    def native_offline_edits(self):
        native = self.native
        income_original = self.hold_editor("income", "6300.00", "amount_yuan")
        native.restart()
        native.open_income()
        native.click("联动工资")
        native.fill("6200.00", previous=r"6,?100(?:\.00)?")
        native.connection(self.port, online=False)
        native.click("保存")
        wait_for(lambda: native.has("原提交") or native.has("等待同步"), "The offline income submission was not retained")
        native.restart()
        native.open_income()
        wait_for(lambda: native.has("6,200") or native.has("6200"), "Reopening lost the original income amount")
        native.capture("income-original-after-offline-reopen")
        assert self.facts()["income_amount"] == 610000
        native.connection(self.port, online=True)
        if native.has("重试原提交"):
            native.click("重试原提交")
        wait_for(lambda: self.facts()["income_amount"] == 620000, "The income original could not resume", 90)
        self.reject_stale_editor("income", income_original)

        goal_original = self.hold_editor("goal", "2500.00", "target_amount_yuan")
        native.restart()
        native.open_goal()
        native.click("编辑目标")
        native.fill("2400.00", previous=r"2,?300(?:\.00)?")
        native.connection(self.port, online=False)
        native.click("保存调整")
        wait_for(lambda: native.has("原提交") or native.has("等待同步"), "The offline goal submission was not retained")
        native.restart()
        native.open_goal()
        wait_for(lambda: native.has("2,400") or native.has("2400"), "Reopening lost the original goal amount")
        native.capture("goal-original-after-offline-reopen")
        assert self.facts()["goal_amount"] == 230000
        native.connection(self.port, online=True)
        if native.has("重试原提交"):
            native.click("重试原提交")
        wait_for(lambda: self.facts()["goal_amount"] == 240000, "The goal original could not resume", 90)
        self.reject_stale_editor("goal", goal_original)

    def hold_editor(self, kind, amount, field):
        family = "income-plans" if kind == "income" else "goals"
        path = f"/web/{family}/{self.facts()[kind + '_id']}/edit"
        form = open_web_editor(self.page, self.base_url, self.ledger_id, path)
        form.locator(f'[name="{field}"]').fill(amount)
        original = {name: form.locator(f'[name="{name}"]').input_value()
                    for name in ("idempotency_key", "expected_row_version", field)}
        return path, original

    def reject_stale_editor(self, kind, saved):
        path, original = saved
        before = self.facts()
        form = self.page.locator(f'form[action="{path}"]')
        with self.page.expect_response(lambda response: response.url == self.base_url + path and response.request.method == "POST") as reply:
            form.locator('button[type="submit"]:not([name])').click()
        assert reply.value.status == 409, "The stale browser editor overwrote the native change"
        self.page.wait_for_function("kind => document.querySelector('[data-' + kind + '-draft-phase]').dataset[kind + 'DraftPhase'] === 'blocked'", arg=kind)
        self.page.reload()
        assert_original(form, original)
        assert self.facts() == before, "A rejected conflict changed stored facts or revisions"
        self.page.screenshot(path=self.evidence / f"web-{kind}-conflict-after-native-edit.png", full_page=True)
        form.locator(f'[data-{kind}-discard]').click()
        self.page.wait_for_url(f"**new_{kind}=1*")

    def web_archive(self, kind):
        facts = self.facts()
        family = "income-plans" if kind == "income" else "goals"
        self.page.goto(f"{self.base_url}/web/{family}?ledger_id={self.ledger_id}")
        action = f"/web/{family}/{facts[kind + '_id']}/archive"
        self.page.locator(f'form[action="{action}"] button[type="submit"]').click()
        wait_for(lambda: self.facts()[kind + "_status"] == "archived", "Web archive did not commit")

    def web_restore(self, kind):
        self.page.goto(f"{self.base_url}/web/recycle-bin?ledger_id={self.ledger_id}")
        api_kind = "income_plan" if kind == "income" else "goal"
        key = f"{api_kind}:{self.facts()[kind + '_id']}"
        self.page.locator(f'[data-restore-key="{key}"] button[type="submit"]').click()
        wait_for(lambda: self.facts()[kind + "_status"] == "active", "Web recycle-bin restore did not commit")

    def native_restore(self, kind, label):
        self.native.recycle_bin()
        wait_for(lambda: self.native.has(label), "The archived plan did not reach the native recycle bin")
        self.native.click_within(label, "恢复")
        self.native.click_within("恢复项目？", "恢复")
        wait_for(lambda: self.facts()[kind + "_status"] == "active", "The native recycle-bin restore did not commit")
        wait_for(lambda: not self.native.has(label), "The restored plan remained in the native recycle bin")

    def archive_restore(self):
        native = self.native
        self.web_archive("income")
        native.open_income()
        native.click("恢复")
        wait_for(lambda: self.facts()["income_status"] == "active", "The native income-list restore did not commit")
        native.restart()
        native.open_income()
        native.click("联动工资")
        native.click("归档")
        wait_for(lambda: self.facts()["income_status"] == "archived", "Native income archive did not commit")
        self.web_restore("income")
        self.web_archive("income")
        self.native_restore("income", "联动工资")
        self.web_archive("goal")
        self.native_restore("goal", "联动消费提醒")
        native.open_goal()
        native.click("归档这个目标")
        native.click("确认归档")
        wait_for(lambda: self.facts()["goal_status"] == "archived", "Native goal archive did not commit")
        self.web_restore("goal")

    def offline_reads(self):
        native = self.native
        native.restart()
        native.open_income()
        native.click("修改记录")
        native.reveal_any("恢复计划")
        native.back()
        native.open_goal()
        native.click("定义历史")
        native.reveal_any("2,400", "2400")
        native.back()
        native.connection(self.port, online=False)
        native.restart()
        native.open_income()
        wait_for(lambda: native.has("本机") or native.has("离线"), "The retained income source was not disclosed")
        native.capture("income-retained-after-recovery")
        native.click("修改记录")
        native.reveal_any("恢复计划")
        native.capture("income-history-after-offline-restart")
        native.back()
        native.open_goal()
        wait_for(lambda: native.has("2,400") or native.has("2400"), "The retained goal detail was lost")
        native.capture("goal-retained-after-recovery")
        native.click("定义历史")
        native.reveal_any("2,400", "2400")
        native.capture("goal-history-after-offline-restart")
        native.back()
        native.connection(self.port, online=True)

    def run(self):
        self.page.on("dialog", lambda dialog: dialog.accept())
        self.web_lost_reply("income", "6100.00", "amount_yuan")
        self.web_lost_reply("goal", "2300.00", "target_amount_yuan")
        self.native_offline_edits()
        self.archive_restore()
        self.offline_reads()
        self.native.plan_home()
        self.native.click("打开账户与设置")
        self.native.click("外观与主题")
        self.native.click("玄夜")
        self.native.open_income()
        self.native.capture("income-midnight")
        self.native.open_goal()
        self.native.capture("goal-midnight")
