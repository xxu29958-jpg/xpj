"""Bilateral relationships exercised through the shipping Web and native consumers."""

from contextlib import closing
from datetime import date
from urllib.parse import urlsplit

from scripts.planning_journey_android import wait_for
from scripts.relationship_journey_facts import facts, pairing_code, seed_identities

CONFIRM = "我已核对份额、已付／已返与免除，并确认本次结算方向和金额。"
SETTLEMENT = "最终待结算（正数由原接收方付，负数由原发送方返）"


class RelationshipJourney:
    def __init__(self, page, native, fixture, evidence, base_url):
        self.page, self.native, self.fixture, self.evidence = page, native, fixture, evidence
        self.base_url = base_url
        self.public_url = base_url.replace("127.0.0.1", "localhost")
        self.port = urlsplit(base_url).port
        self.identity = seed_identities(fixture.ledger_id)
        self.receiver = None

    def facts(self):
        return facts(self.identity)

    def expect(self, field, value):
        wait_for(lambda: self.facts().get(field) == value, f"Relationship fact did not become {field}={value}", 90)

    def goto(self, path, *, receiver=False):
        page = self.receiver if receiver else self.page
        ledger = self.identity.receiver_ledger if receiver else self.identity.sender_ledger
        base = self.public_url if receiver else self.base_url
        return page.goto(f"{base}{path}{'&' if '?' in path else '?'}ledger_id={ledger}")

    def capture(self, name, *, receiver=False):
        page = self.receiver if receiver else self.page
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "The actual relationship page overflows"
        page.screenshot(path=self.evidence / f"web-relationship-{name}.png", full_page=True)

    def connect(self, page, account_id, *, next_path="/web/bill-splits/inbox"):
        code = pairing_code(self.identity.receiver_ledger, account_id)
        page.goto(f"{self.public_url}/web/auth/login?next={next_path}")
        page.locator('[name="pairing_code"]').fill(code)
        page.locator('form[action="/web/auth/login"] button[type="submit"]').click()
        page.wait_for_url(f"**{next_path}*")

    def create_relationship(self):
        page = self.page
        page.goto(self.base_url + "/web/auth/local?next=/web/expenses/new")
        page.locator(f'input[name="ledger_id"][value="{self.fixture.ledger_id}"]').check()
        page.locator('form[action="/web/auth/local"] button[type="submit"]').click()
        page.wait_for_url("**/web/expenses/new*")
        form = page.locator('form[action="/web/expenses/new"]')
        form.locator('[name="amount_major"]').fill("100.00")
        options = form.locator("details.manual-expense-options")
        if not form.locator('[name="merchant"]').is_visible():
            options.locator(":scope > summary").click()
        form.locator('[name="merchant"]').fill("往来联动原单")
        form.get_by_role("button", name="记下这笔支出", exact=True).click()
        self.expect("source_amount", 10000)
        source = self.facts()["source_id"]
        self.goto(f"/web/expenses/{source}/edit")
        invite = page.locator(f'form[action="/web/expenses/{source}/split-invite"]')
        invite.locator('[name="receiver_account_id"]').select_option(str(self.identity.receiver_account))
        invite.locator('[name="amount_yuan"]').fill("40.00")
        invite.get_by_role("button", name="发起拆账", exact=True).click()
        self.expect("invitation_status", "invited")
        self.connect(self.receiver, self.identity.receiver_account)
        invitation = self.facts()["invitation_id"]
        accept = self.receiver.locator(f'form[action="/web/bill-splits/{invitation}/accept"]')
        assert accept.locator('[name="target_ledger_id"]').input_value() == self.identity.receiver_ledger
        accept.get_by_role("button", name="接受并记账", exact=True).click()
        self.expect("invitation_status", "accepted")
        self.expect("received_amount", 4000)
        assert self.facts()["expenses"] == 2 and self.facts()["original_principal"] == 4000
        self.receiver.get_by_role("link", name="查看这笔往来", exact=True).click()
        self.capture("received-invitation", receiver=True)
        self.native.bind(pairing_code(self.identity.receiver_ledger, self.identity.receiver_account), self.port)

    def open_native(self, *, returned=False):
        self.native.plan_home()
        self.native.click("往来", bottom=True)
        self.native.click("欠我" if returned else "我欠")
        self.native.reveal_any("联动验证账户")
        self.native.click("联动验证账户", stable=True)
        self.native.reveal_any("看看账")

    def native_confirmation(self):
        self.native.reveal_any(CONFIRM)
        checkboxes = [node for node in self.native.tree().iter("node") if node.attrib.get("checkable") == "true"]
        assert len(checkboxes) == 1, "The current agreement confirmation must be unambiguous"
        assert checkboxes[0].attrib.get("enabled") == "true", "A fresh relationship cannot be confirmed"
        if checkboxes[0].attrib.get("checked") != "true":
            self.native.tap(checkboxes[0])

    def native_accept(self, expected_share):
        self.native.restart()
        self.open_native()
        self.native.reveal_any("重新核对约定")
        self.native.click("重新核对约定")
        self.native_confirmation()
        self.native.click("接受新约定")
        self.expect("agreed_share", expected_share)
        self.native.capture("accepted-agreement")

    def partial_payment_and_refund(self):
        self.open_native()
        self.native.reveal_any("提交还款确认")
        self.native.click("提交还款确认")
        self.native.fill("30.00", label="金额")
        self.native.click("保存")
        original = self.facts()["original_id"]
        wait_for(lambda: original in self.facts()["pending_repayments"], "Native repayment declaration was not retained")
        self.goto(f"/web/debts/{original}")
        self.page.get_by_role("button", name="确认到账", exact=True).click()
        self.expect("original_paid", 3000)
        self.goto(f"/web/debts/{original}")
        self.page.get_by_text("免除这笔往来", exact=True).click()
        self.page.get_by_role("button", name="确认免除", exact=True).click()
        self.expect("original_forgiven", 1000)
        self.expect("original_remaining", 0)
        self.goto(f"/web/expenses/{self.facts()['source_id']}/edit")
        panel = self.page.locator("#offset-create-money")
        panel.locator("summary").click()
        panel.locator('[name="original_amount"]').fill("60.00")
        panel.locator('[name="accounting_date"]').fill(date.today().isoformat())
        panel.locator('[name="reason"]').fill("商家部分退款，双方另行核对承担")
        panel.get_by_role("button", name="登记", exact=True).click()
        self.expect("offsets", 1)
        self.expect("source_refund", 6000)
        self.expect("agreed_share", 4000)
        assert self.facts()["received_amount"] == 4000 and self.facts()["source_amount"] == 10000
        self.capture("source-refund-keeps-agreement")

    def agreement_form(self, *, receiver=False, returned=False, command="create"):
        current = self.facts()
        public_id = current["return_id" if returned else "original_id"]
        self.goto(f"/web/debts/{public_id}/split-agreement?command={command}", receiver=receiver)
        page = self.receiver if receiver else self.page
        form = page.locator('[data-repayment-kind="split-change"]')
        form.locator("[data-repayment-submit]").wait_for(state="visible")
        return form

    def propose_web(self, share, settlement, reason, *, receiver=False, returned=False):
        form = self.agreement_form(receiver=receiver, returned=returned)
        form.locator('[name="new_share_amount_major"]').fill(share)
        form.locator('[name="settlement_net_amount_major"]').fill(settlement)
        form.locator('[name="reason"]').fill(reason)
        form.locator("[data-repayment-preview]").click()
        page = self.receiver if receiver else self.page
        page.wait_for_load_state()
        form = page.locator('[data-repayment-kind="split-change"]')
        assert form.locator('[name="settlement_net_amount_major"]').input_value() == settlement
        form.locator("[data-repayment-submit]").click()
        wait_for(lambda: self.facts()["pending_id"], "The actual split proposal was not committed")

    def settle_return(self):
        returned = self.facts()["return_id"]
        self.goto("/web/debts")
        assert self.page.locator(f'a[href*="/web/debts/{returned}"]').count() > 0, "The sender cannot discover the cross-ledger return payable"
        self.goto(f"/web/debts/{returned}")
        self.page.locator('[name="amount_major"]').fill("2.00")
        self.page.get_by_role("button", name="提交还款确认", exact=True).click()
        wait_for(lambda: returned in self.facts()["pending_repayments"], "The return declaration was not retained")
        self.native.restart()
        self.open_native(returned=True)
        self.native.reveal_any("收到啦，谢谢～")
        self.native.click("收到啦，谢谢～")
        self.native.click("保存")
        self.expect("return_paid", 200)
        self.native.reveal_any("算了，不用还了")
        self.native.click("算了，不用还了")
        self.native.click("嗯，这份我请")
        self.expect("return_forgiven", 100)
        self.expect("settlement", 0)

    def run(self):
        from scripts.relationship_journey_recovery import RelationshipRecovery
        from scripts.relationship_journey_views import goal_entry

        with closing(self.page.context.browser.new_context(viewport={"width": 1280, "height": 960})) as context:
            self.receiver = context.new_page()
            self.create_relationship()
            goal_entry(self, create=True)
            self.partial_payment_and_refund()
            self.propose_web("20.00", "-3.00", "保留已付款和免除，明确返还三元")
            self.native_accept(2000)
            self.expect("settlement", -300)
            first_change = self.facts()["changes"][0]
            first_proposal = self.facts()["proposals"][0]
            returned = self.facts()["return_id"]
            self.settle_return()
            RelationshipRecovery(self).run()
            result = self.facts()
            assert result["changes"][0] == first_change and result["return_id"] == returned
            assert result["proposals"][0] == first_proposal
            assert result["original_principal"] == result["received_amount"] == 4000
            assert result["source_amount"] == 10000 and result["expenses"] == 2 and result["offsets"] == 1
            assert (result["original_paid"], result["original_forgiven"], result["return_paid"], result["return_forgiven"]) == (3000, 1000, 200, 100)
            assert result["return_count"] == 1 and result["repayments"] == 2
            result["verified_leg"] = "Bilateral invitation, repayment, source refund, explicit agreement, return and forgiveness, immutable histories, both clients and recovery"
            return result
