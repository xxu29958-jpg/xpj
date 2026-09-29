"""Original submissions, bilateral history and role boundaries in the real journey."""

from scripts.planning_journey_android import wait_for
from scripts.relationship_journey import SETTLEMENT


def form_values(form):
    return form.evaluate("form => Object.fromEntries(new FormData(form).entries())")


class RelationshipRecovery:
    def __init__(self, journey):
        self.j = journey

    def native_original(self):
        j, native = self.j, self.j.native
        j.open_native(returned=True)
        native.reveal_any("新约定份额")
        native.fill("12.00", label="新约定份额（CNY）")
        native.reveal_any(SETTLEMENT)
        native.fill("-4.00", label=SETTLEMENT)
        native.reveal_any("原因")
        native.fill("native-reopen-12", label="原因")
        native.reveal_any("预览新份额的结算", toward_start=True)
        native.click("预览新份额的结算")
        j.native_confirmation()
        native.connection(j.port, online=False)
        native.click("提出新约定")
        native.reveal_any("原提交原因：native-reopen-12")
        native.capture("relationship-offline-original")
        assert j.facts()["pending_id"] is None, "An offline intent was mistaken for a server proposal"
        native.restart()
        j.open_native(returned=True)
        native.reveal_any("原提交原因：native-reopen-12")
        native.capture("relationship-original-after-restart")
        native.connection(j.port, online=True)
        if j.facts()["pending_id"] is None and native.has("重试原提交"):
            native.click("重试原提交")
        wait_for(lambda: j.facts()["pending_id"], "The original Room intent did not resume", 90)
        submitted = j.facts()["proposals"][-1]
        assert (submitted["reason"], submitted["new_share_amount_cents"], submitted["settlement_net_amount_cents"]) == (
            "native-reopen-12", 1200, -400)
        assert sum(row["reason"] == "native-reopen-12" for row in j.facts()["proposals"]) == 1

    def lost_acceptance_reply(self):
        j, page = self.j, self.j.page
        form = j.agreement_form(command="accept")
        original = form_values(form)
        path = form.get_attribute("action")
        before = len(j.facts()["changes"])
        delivered = []

        def lose_reply(route):
            response = route.fetch(max_redirects=0)
            assert response.status == 200 and "data-repayment-ack=" in response.text()
            delivered.append(True)
            route.abort("connectionclosed")

        page.route("**" + path, lose_reply)
        with page.expect_event("requestfailed", predicate=lambda request: request.url.endswith(path)):
            form.locator("[data-repayment-submit]").click()
        j.expect("agreed_share", 1200)
        assert delivered == [True]
        page.unroute("**" + path, lose_reply)
        form = j.agreement_form()
        restored = form_values(form)
        assert {k: v for k, v in restored.items() if k != "csrf_token"} == {
            k: v for k, v in original.items() if k != "csrf_token"}, "Lost reply changed the original acceptance"
        j.capture("acceptance-lost-reply-original")
        form.locator("[data-repayment-submit]").click()
        page.locator("[data-repayment-ack]").wait_for()
        assert len(j.facts()["changes"]) == before + 1
        wait_for(lambda: page.evaluate("ref => localStorage.getItem('ticketbox:split-change-draft:v1:' + ref) === null",
            original["idempotency_key"]), "The matching original acceptance receipt did not close the draft")

    def crossed_versions(self):
        j = self.j
        stale = j.agreement_form(receiver=True, returned=True)
        stale.locator('[name="new_share_amount_major"]').fill("14.00")
        stale.locator('[name="settlement_net_amount_major"]').fill("-1.00")
        stale.locator('[name="reason"]').fill("另一端修改后继续原填写")
        original = form_values(stale)
        self.native_original()
        self.lost_acceptance_reply()
        assert len(j.facts()["changes"]) == 2 and j.facts()["settlement"] == -400
        stale.locator("[data-repayment-submit]").click()
        replacement = j.receiver.locator("[data-repayment-replace]")
        replacement.wait_for(state="visible")
        blocked = j.receiver.locator('[data-repayment-kind="split-change"]')
        retained = form_values(blocked)
        assert all(retained[name] == original[name] for name in (
            "idempotency_key", "expected_row_version", "expected_return_row_version", "new_share_amount_major",
            "settlement_net_amount_major", "reason", "origin_binding")), "A version conflict rewrote the original submission"
        assert j.facts()["pending_id"] is None
        j.capture("stale-two-leg-original", receiver=True)
        replacement.click()
        corrected = form_values(blocked)
        assert corrected["idempotency_key"] != original["idempotency_key"]
        assert corrected["expected_return_row_version"] != original["expected_return_row_version"]
        assert corrected["settlement_net_amount_major"] == "-1.00" and corrected["new_share_amount_major"] == "14.00"
        assert j.facts()["pending_id"] is None, "Review submitted a new agreement without the user's command"
        blocked.locator("[data-repayment-submit]").click()
        wait_for(lambda: j.facts()["pending_id"], "The corrected explicit command was not submitted")
        accepted = j.agreement_form(command="accept")
        accepted.locator("[data-repayment-submit]").click()
        j.expect("agreed_share", 1400)
        j.expect("settlement", -100)

    def resolutions(self):
        j = self.j
        j.propose_web("14.00", "-1.00", "旧提议等待另拟")
        previous = j.facts()["pending_id"]
        j.goto(f"/web/debts/{j.facts()['original_id']}/split-agreement", receiver=True)
        j.receiver.get_by_role("link", name="另拟一份并替代此提议", exact=True).click()
        form = j.receiver.locator('[data-repayment-kind="split-change"]')
        assert form.locator('[name="supersedes_proposal_public_id"]').input_value() == previous
        form.locator('[name="reason"]').fill("双方另拟的提议")
        form.locator("[data-repayment-submit]").click()
        wait_for(lambda: j.facts()["pending_id"] not in (None, previous), "The explicit replacement did not supersede the proposal")
        assert next(row for row in j.facts()["proposals"] if row["public_id"] == previous)["status"] == "superseded"
        form = j.agreement_form(receiver=True, command="withdraw")
        form.locator("[data-repayment-submit]").click()
        j.expect("pending_id", None)
        j.propose_web("14.00", "-1.00", "由原生拒绝的一份提议")
        j.native.restart()
        j.open_native()
        j.native.reveal_any("拒绝提议")
        j.native.click("拒绝提议")
        j.expect("pending_id", None)
        assert j.facts()["proposals"][-1]["status"] == "rejected"
        # Web reads 20 rows per page, while native uses the API default of 50.
        # Both legs must cross the larger boundary through actual UI decisions.
        for index in range(17):
            j.propose_web("14.00", "-1.00", f"保留原历史的撤回 {index + 1}")
            form = j.agreement_form(command="withdraw")
            form.locator("[data-repayment-submit]").click()
            j.expect("pending_id", None)
        assert len(j.facts()["changes"]) == 3 and j.facts()["settlement"] == -100

    def histories_and_roles(self):
        from scripts.relationship_journey_views import verify_views

        verify_views(self.j)

    def run(self):
        self.crossed_versions()
        self.resolutions()
        self.histories_and_roles()
