"""Only an original creation receipt may acknowledge a browser's saved intent."""

from types import SimpleNamespace

import pytest

from app.services import manual_expense_draft_presenter as presenter


@pytest.mark.parametrize("receipt_id", [None, 99, 7])
def test_opening_current_fact_requires_matching_original_receipt_before_draft_ack(monkeypatch, receipt_id):
    auth = SimpleNamespace(device_id=41, ledger_id="ledger")
    ref = "a" * 32
    # This is the later current fact, not the first accepted response.
    expense = SimpleNamespace(id=7, tenant_id="ledger", source="手动记账",
        draft_idempotency_key=f"41:{ref}", amount_cents=9900, row_version=4)
    receipt = None if receipt_id is None else SimpleNamespace(id=receipt_id, amount_cents=1200, row_version=1)
    monkeypatch.setattr(presenter, "read_manual_creation_receipt", lambda *_a, **_k: receipt, raising=False)
    scope = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account",
        "ledgerId": "ledger", "deviceId": "device"}
    monkeypatch.setattr(presenter, "manual_draft_scope", lambda *_a: scope)

    ack = presenter.manual_draft_ack(object(), auth, expense)

    assert ack == ({"scope": scope, "clientRef": ref} if receipt_id == expense.id else None)
