"""Lose a committed OCR reply from the real drawer and replay its original key."""

def open_recognition_task(j, amount, note):
    draft = j.page.locator('form[data-expensereview-draft-scope]')
    for name, value in (("amount_yuan", amount), ("note", note)):
        field = draft.locator(f'[name="{name}"]')
        for disclosure in field.locator("xpath=ancestor::details").all():
            if disclosure.get_attribute("open") is None:
                disclosure.locator(":scope > summary").click()
        field.fill(value)
    link = j.page.locator(f'a[href^="/web/expenses/{j.expense_id}/ocr/retry?"]')
    for disclosure in link.locator("xpath=ancestor::details").all():
        if disclosure.get_attribute("open") is None:
            disclosure.locator(":scope > summary").click()
    link.click()
    j.page.wait_for_function("document.querySelector('[data-recognition-form]')?.expenseReviewContinuity")
    return j.page.locator('form[data-recognition-form]')


def drawer_lost_ocr_reply(j):
    j.goto("/web/pending")
    j.page.locator(f'a.exp-row-detail[href^="/web/expenses/{j.expense_id}/edit?"]').click()
    draft = j.page.locator("form[data-drawer-form]")
    draft.wait_for(state="visible")
    path = f"/web/expenses/{j.expense_id}/ocr/retry"
    retry = open_recognition_task(j, "20.00", "抽屉尚未保存的核对")
    original_key = retry.locator('[name="idempotency_key"]').input_value()
    original_version = retry.locator('[name="expected_row_version"]').input_value()
    delivered = []

    def lose_reply(route):
        response = route.fetch(max_redirects=0)
        assert response.status == 200 and response.json()["receipt"]["accepted"], "OCR was not accepted before losing its reply"
        route.abort("connectionclosed")
        delivered.append(True)

    j.page.context.route("**" + path, lose_reply)
    try:
        retry.get_by_role("button", name="重新识别原件", exact=True).click()
        j.page.get_by_text("暂未收到保存回执。", exact=False).wait_for()
        assert delivered == [True], "The real OCR command was not delivered before reply loss"
    finally:
        j.page.context.unroute("**" + path, lose_reply)
    accepted = j.facts()
    assert accepted["expenses"][0]["version"] > int(original_version)
    j.page.reload()
    j.page.wait_for_function("document.querySelector('[data-recognition-form]')?.expenseReviewContinuity")
    assert retry.locator('[name="idempotency_key"]').input_value() == original_key
    assert retry.locator('[name="expected_row_version"]').input_value() == original_version
    j.capture("drawer-ocr-lost-reply-original-retained")
    retry.get_by_role("button", name="核实这次识别结果", exact=True).click()
    j.page.wait_for_url("**/edit?*")
    j.page.wait_for_function("document.querySelector('[name=amount_yuan]').value === '20.00'")
    draft = j.page.locator('form[data-expensereview-draft-scope]')
    assert draft.locator('[name="note"]').input_value() == "抽屉尚未保存的核对"
    assert j.facts() == accepted, "Replaying the original OCR key wrote a second result"
    assert accepted["expenses"][0]["amount"] == 1851
    j.capture("drawer-ocr-original-receipt-recovered")
