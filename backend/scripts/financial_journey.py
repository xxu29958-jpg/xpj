"""One fact across real Web forms, native Room/Outbox and PostgreSQL."""

from email import policy
from email.parser import BytesParser
from urllib.parse import parse_qsl, urlsplit

from scripts.financial_journey_facts import facts
from scripts.planning_journey_android import wait_for
from scripts.portable_journey_facts import attach_fixture_original


def _submitted_fields(request):
    content_type = request.headers.get("content-type", "")
    body = request.post_data_buffer or b""
    if "multipart/form-data" in content_type:
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body)
        fields = [(part.get_param("name", header="content-disposition"),
            part.get_payload(decode=True).decode()) for part in message.iter_parts()]
    else:
        fields = parse_qsl(body.decode(), keep_blank_values=True)
    return [(name, value) for name, value in fields if name != "csrf_token"]


class FinancialJourney:
    def __init__(self, page, native, fixture, evidence, base_url, restart_backend):
        self.page, self.native, self.fixture, self.evidence = page, native, fixture, evidence
        self.base_url, self.port = base_url, urlsplit(base_url).port
        self.restart_backend = restart_backend
        self.original_digest = ""

    def facts(self):
        return facts(self.fixture.ledger_id)

    def expect(self, predicate, reason):
        return wait_for(lambda: predicate(self.facts()), reason, 90)

    def goto(self, path):
        response = self.page.goto(f"{self.base_url}{path}{'&' if '?' in path else '?'}ledger_id={self.fixture.ledger_id}")
        assert response.ok, f"The actual financial consumer failed: {path} ({response.status})"

    def form(self, action):
        return self.page.locator(f'form[action="{action}"]')

    def capture(self, name):
        assert not self.page.evaluate("document.documentElement.scrollWidth > innerWidth"), "The financial page overflows"
        self.page.screenshot(path=self.evidence / f"web-financial-{name}.png", full_page=True)

    def native_open(self):
        self.native.domain_home("流水")
        self.native.click(self.facts()["merchant"])
        wait_for(lambda: self.native.has("更正这笔账单"), "The native fact did not open")

    def correction(self):
        state = self.facts()
        self.goto(f'/web/expenses/{state["id"]}/correct?return_to=search&return_query=Fact')
        form = self.form(f'/web/expenses/{state["id"]}/corrections')
        wait_for(lambda: form.locator('[name="reason"]').get_attribute("readonly") is None,
            "The Web draft lease was not acquired")
        return form

    def commit_web_correction(self, values, *, split=False):
        before = self.facts()
        form = self.correction()
        for name, value in values.items():
            form.locator(f'[name="{name}"]').fill(value)
        if split:
            form.locator('[name="split_member_id"]').first.locator("xpath=ancestor::details").locator("summary").click()
            form.locator('[name="split_member_id"]').first.select_option(index=1)
            form.locator('[name="split_amount_yuan"]').first.fill("6.00")
            form.locator('[name="split_note"]').first.fill("SplitKeep")
        form.locator("[data-correction-submit]").click()
        self.expect(lambda state: len(state["revisions"]) == len(before["revisions"]) + 1,
            "The actual Web correction did not commit exactly once")
        self.page.wait_for_url("**/edit?*")

    def initial_fact(self):
        page = self.page
        page.goto(self.base_url + "/web/auth/local?next=/web/expenses/new")
        page.locator(f'input[name="ledger_id"][value="{self.fixture.ledger_id}"]').check()
        self.form("/web/auth/local").locator('button[type="submit"]').click()
        page.wait_for_url("**/web/expenses/new*")
        form = self.form("/web/expenses/new")
        form.locator('[name="amount_major"]').fill("12.34")
        if not form.locator('[name="merchant"]').is_visible():
            form.locator("details.manual-expense-options > summary").click()
        form.locator('[name="merchant"]').fill("FactStart")
        form.locator('[name="category"]').fill("餐饮")
        form.get_by_role("button", name="记下这笔支出", exact=True).click()
        self.expect(lambda state: len(state["expenses"]) == 1, "The real manual expense did not commit")
        self.original_digest = attach_fixture_original(self.facts()["id"], ledger_id=self.fixture.ledger_id)
        self.native.bind(self.fixture.pairing_code, self.port)
        self.native_open()

    def native_retained_correction(self):
        native = self.native
        native.click("更正这笔账单")
        native.fill("NativeDraft", label="更正原因（必填）")
        native.reveal_any("商家")
        native.fill("NativeShop", previous="FactStart")
        native.click("保留原稿并关闭")
        native.restart()
        self.native_open()
        native.click("继续更正账单")
        assert native.has("NativeDraft") and native.has("NativeShop"), "A cold native reopen lost the original text"
        native.capture("financial-correction-original-after-restart")
        native.click("保留原稿并关闭")
        self.commit_web_correction({"reason": "WebAmount", "amount_yuan": "15.00", "note": "PeerNote"}, split=True)
        split = self.facts()["splits"]
        self.native_open()
        native.click("继续更正账单")
        native.reveal_any("按以上选择继续核对")
        native.capture("financial-correction-current-beside-original")
        native.click("按以上选择继续核对")
        native.click("保存更正")
        self.expect(lambda state: state["merchant"] == "NativeShop", "The reviewed native input did not reach the fact owner")
        state = self.facts()
        assert state["amount"] == 1500 and state["note"] == "PeerNote", "Native review overwrote untouched peer fields"
        assert state["splits"] == split, "Native review replaced the peer's untouched split identities"

    def web_conflict_and_original_receipt(self):
        page, native = self.page, self.native
        form = self.correction()
        form.locator('[name="merchant"]').fill("WebFinal")
        form.locator('[name="reason"]').fill("WebDraft")
        form.locator('[name="amount_yuan"]').fill(" 0017.25 ")
        original_key = form.locator('[name="idempotency_key"]').input_value()
        original_ref = form.locator('[name="draft_client_ref"]').input_value()
        self.native_open()
        native.click("更正这笔账单")
        native.fill("NativeNote", label="更正原因（必填）")
        native.reveal_any("备注")
        native.fill("LaterNote", previous="PeerNote")
        native.click("保存更正")
        self.expect(lambda state: state["note"] == "LaterNote", "The peer correction did not commit")
        before = self.facts()
        page.reload()
        wait_for(lambda: form.locator('[name="reason"]').input_value() == "WebDraft", "The Web original did not reopen")
        assert form.locator('[name="idempotency_key"]').input_value() == original_key
        form.locator("[data-correction-submit]").click()
        page.wait_for_function("document.querySelector('[data-correction-draft-phase]').dataset.correctionDraftPhase === 'blocked'")
        assert self.facts() == before, "A stale correction wrote financial facts"
        self.capture("correction-stale-original")
        form.locator("[data-correction-review]").click()
        page.get_by_text("已采用当前版本作为依据", exact=False).wait_for()
        assert self.facts() == before, "Review wrote financial facts"
        assert form.locator('[name="amount_yuan"]').input_value() == " 0017.25 "
        assert form.locator('[name="note"]').input_value() == "LaterNote"
        assert form.locator('[name="idempotency_key"]').input_value() != original_key
        assert form.locator('[name="draft_client_ref"]').input_value() == original_ref
        self.capture("correction-reviewed-original")
        self.lost_reply(form, "[data-correction-submit]", "/corrections", "correction")
        after = self.facts()
        assert (after["merchant"], after["amount"], after["note"]) == ("WebFinal", 1725, "LaterNote")
        assert len(after["revisions"]) == len(before["revisions"]) + 1 and after["splits"] == before["splits"]

    def lost_reply(self, form, submit, suffix, family):
        path = f'/web/expenses/{self.facts()["id"]}{suffix}'
        sent = []

        def lose_first(route):
            sent.append(_submitted_fields(route.request))
            if len(sent) == 1:
                accepted = route.fetch(max_redirects=0)
                assert accepted.status == 200, "The real fact command was not accepted before reply loss"
                route.abort("connectionclosed")
            else:
                route.continue_()

        self.page.route("**" + path, lose_first)
        form.locator(submit).click()
        form.get_by_text("暂未收到保存回执。", exact=False).wait_for()
        committed = self.facts()
        self.capture(f"{family}-accepted-reply-lost")
        self.page.reload()
        form.locator(submit).click()
        self.page.wait_for_url("**/edit?*")
        self.page.unroute("**" + path, lose_first)
        assert len(sent) == 2 and sent[0] == sent[1], "Retry changed the original financial command"
        assert self.facts() == committed, "Replaying an accepted command wrote another fact"

    def native_refund_offline(self):
        native = self.native
        self.native_open()
        native.click("登记退款")
        native.fill("3.00", label="退回金额（CNY）")
        native.fill("NativeRefund", label="原因（必填）")
        native.click("保留原稿并关闭")
        native.connection(self.port, online=False)
        try:
            native.restart()
            self.native_open()
            native.reveal_any("显示上次读取的历史")
            native.capture("financial-history-cold-offline")
            native.reveal_any("继续登记退款", toward_start=True)
            native.click("继续登记退款")
            assert native.has("NativeRefund") and native.has("3.00"), "The cold refund draft lost its raw fields"
            native.click("登记退款", bottom=True)
            wait_for(lambda: native.has("原操作已保存") or native.has("待同步"), "The offline refund was not retained")
            assert self.facts()["offsets"] == [], "An offline intent was presented as a committed refund"
            native.capture("financial-refund-offline-submission")
            native.restart()
        finally:
            native.connection(self.port, online=True)
        self.expect(lambda state: len(state["offsets"]) == 1, "The retained native refund did not resume")
        state = self.facts()
        assert state["offsets"][0]["amount"] == 300 and state["net"] == 1425
        assert state["offsets"][0]["reason"] == "NativeRefund"

    def web_void_and_reversal(self):
        state = self.facts()
        offset = state["offsets"][0]
        self.goto(f'/web/expenses/{state["id"]}/edit')
        suffix = f'/offsets/{offset["public_id"]}/voids'
        form = self.form(f'/web/expenses/{state["id"]}{suffix}')
        form.locator("xpath=ancestor::details").locator("summary").click()
        form.locator('[name="void_reason"]').fill("RefundRecalled")
        self.lost_reply(form, "[data-offset-submit]", suffix, "void")
        assert self.facts()["net"] == 1725 and self.facts()["offsets"][0]["status"] == "voided"
        self.page.locator("#offset-create-reversal > summary").click()
        reversal = self.page.locator(f'form[data-offset-plan-id="{state["id"]}:reversal"]')
        reversal.locator('[name="reason"]').fill("DuplicateFact")
        self.lost_reply(reversal, "[data-offset-submit]", "/offsets", "reversal")
        state = self.facts()
        assert state["net"] == 0 and len(state["offsets"]) == 2
        reversal_id = state["offsets"][1]["public_id"]
        form = self.form(f'/web/expenses/{state["id"]}/offsets/{reversal_id}/voids')
        form.locator("xpath=ancestor::details").locator("summary").click()
        form.locator('[name="void_reason"]').fill("KeepFact")
        form.locator("[data-offset-submit]").click()
        self.expect(lambda value: value["net"] == 1725, "Voiding the reversal did not restore the original contribution")
        assert len(self.facts()["offset_history"]) == 4

    def run(self):
        from scripts.financial_journey_views import appearances, consumers

        self.initial_fact()
        original = self.facts()["image_hash"]
        self.native_retained_correction()
        self.web_conflict_and_original_receipt()
        self.native_refund_offline()
        consumers(self, expected_net=1425)
        self.web_void_and_reversal()
        before_restart = self.facts()
        self.restart_backend()
        assert self.facts() == before_restart, "Restart changed the accepted fact or retained history"
        consumers(self, expected_net=1725)
        appearances(self)
        result = self.facts()
        assert result["image_hash"] == original and result["original_attached"]
        result.update(original_sha256=self.original_digest, verified_leg="Actual Web/native financial corrections, original-input cold reopen, cross-client review, accepted reply loss, offline Room/Outbox refund, offset void/reversal, immutable history, restart and query consumers")
        return result
