"""New time intent cannot alter an old command body or an accepted receipt."""

from types import SimpleNamespace

from test_manual_create_receipt import _expense

from app.schemas import ExpenseCorrectionRequest, ExpenseManualCreateRequest, ExpenseResponse
from app.services.expense_correction_service import correction_idempotency_body
from app.services.manual_expense_receipt import _manual_receipt, _manual_request_fingerprint


def test_old_manual_fingerprint_keeps_absent_and_explicit_null_time():
    payload = ExpenseManualCreateRequest(client_ref="original-ref", home_currency_code="JPY",
        original_currency="JPY", original_amount="12", category="餐饮")
    assert _manual_request_fingerprint(payload) == "69d4366d334edb81a7660210407e46b9b49f4b8dfe26b9817336b987c5382c9d"
    assert "time_input" not in payload.model_dump(exclude_unset=True)
    cleared = payload.model_copy(update={"expense_time": None})
    assert _manual_request_fingerprint(cleared) == "a9cf7add3992c5ff24cbf34a18f92c914e13325ce7be836c45ddd368f0c28d74"


def test_time_intent_is_part_of_original_command_and_correction_body():
    intent = {"precision": "date_only", "calendar_revision": 2, "user_local_date": "2026-04-30"}
    old = ExpenseManualCreateRequest(client_ref="original-ref", amount_cents=1234)
    new = ExpenseManualCreateRequest(client_ref="original-ref", amount_cents=1234, time_input=intent)
    assert _manual_request_fingerprint(new) != _manual_request_fingerprint(old)
    correction = ExpenseCorrectionRequest(expected_row_version=3, reason="修正日期", time_input=intent)
    body = correction_idempotency_body(correction, actor_account_id=7)
    assert body["time_input"] == intent
    assert "expense_time" not in body
    cleared = ExpenseCorrectionRequest(expected_row_version=3, reason="清除时间", time_input=None)
    assert correction_idempotency_body(cleared, actor_account_id=7)["time_input"] is None


def test_old_accepted_receipt_keeps_missing_time_evidence_missing():
    original = ExpenseResponse.model_validate(_expense()).model_dump(mode="json")
    original.pop("accounting_time", None)
    receipt = _manual_receipt(SimpleNamespace(response_body=original, operation="create_manual_expense",
        resource_type="expense", resource_id="42"))
    assert receipt.accounting_time is None
    assert receipt.model_dump(mode="json") == original
