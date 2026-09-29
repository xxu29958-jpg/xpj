"""Lose a committed OCR reply from the real drawer and replay its original key."""

from scripts.planning_journey_android import wait_for


def drawer_lost_ocr_reply(j):
    j.goto("/web/pending")
    j.page.locator(f'a.exp-row-detail[href^="/web/expenses/{j.expense_id}/edit?"]').click()
    draft = j.page.locator("form[data-drawer-form]")
    draft.wait_for(state="visible")
    draft.locator('[name="amount_yuan"]').fill("20.00")
    draft.locator('[name="note"]').fill("抽屉尚未保存的核对")
    path = f"/web/expenses/{j.expense_id}/ocr/retry"
    retry = j.page.locator(f'form[action="{path}"]')
    original_key = retry.locator('[name="idempotency_key"]').input_value()
    original_version = retry.locator('[name="expected_row_version"]').input_value()
    delivered = []

    def lose_reply(route):
        response = route.fetch(max_redirects=0)
        assert response.status == 303, "OCR was not accepted before losing its reply"
        delivered.append(True)
        route.abort("connectionclosed")

    # The command opens a popup; its first request belongs to the browser context.
    j.page.context.route("**" + path, lose_reply)
    try:
        with j.page.expect_popup() as popup:
            retry.get_by_role("button", name="重试识别", exact=True).click()
        lost = popup.value
        wait_for(lambda: delivered, "The real OCR command was not delivered")
        lost.close()
    finally:
        j.page.context.unroute("**" + path, lose_reply)
    accepted = j.facts()
    assert accepted["expenses"][0]["version"] > int(original_version)
    assert retry.locator('[name="idempotency_key"]').input_value() == original_key
    assert retry.locator('[name="expected_row_version"]').input_value() == original_version
    assert draft.locator('[name="amount_yuan"]').input_value() == "20.00"
    assert draft.locator('[name="note"]').input_value() == "抽屉尚未保存的核对"
    j.capture("drawer-ocr-lost-reply-original-retained")
    with j.page.expect_popup() as popup:
        retry.get_by_role("button", name="重试识别", exact=True).click()
    recovered = popup.value
    try:
        recovered.wait_for_url("**/edit?*")
        assert recovered.locator('[name="amount_yuan"]').input_value() == "18.51"
        assert j.facts() == accepted, "Replaying the original OCR key wrote a second result"
        assert draft.locator('[name="amount_yuan"]').input_value() == "20.00"
        j.capture("drawer-ocr-original-receipt-recovered", page=recovered)
    finally:
        recovered.close()
