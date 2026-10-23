"""ADR-0049 §杠杆③ NLS repayment-capture inbox — capture / list / dismiss (slice 3a).

The Android NLS captures a *repayment* notification as a PENDING draft (never an
auto-recorded fact, §8). This file pins capture + the review inbox + dismiss; the
confirm-into-a-Debt path lives in ``test_repayment_drafts_confirm.py`` (split to keep
each file under the 500-line layering budget).

- capture: content+identity dedup (re-posted notification → one draft; distinct posts →
  distinct drafts), invalid channel → 422, viewer → 403, no-auth → 401.
- list: the pending inbox, status-filtered.
- dismiss: latches dismissed (idempotent if already dismissed), no-auth → 401.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Account, Debt
from app.services import debt_service
from app.services.time_service import now_utc
from tests._runtime_protocol import negotiated_headers
from tests.debt_proposal_helpers import capture_repayment_draft
from tests.family_ledger_test_support import set_owner_ledger_role

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


# --- capture --------------------------------------------------------------------


def test_capture_creates_pending_draft(client: TestClient, *, identity) -> None:
    draft = capture_repayment_draft(client, identity, amount_cents=30000, merchant_label='借呗')
    assert draft["status"] == "pending"
    assert draft["source"] == "alipay"
    assert draft["amount_cents"] == 30000
    assert draft["home_currency_code"] == "CNY"
    assert draft["merchant_label"] == "借呗"
    assert draft["committed_debt_public_id"] is None
    assert draft["committed_repayment_public_id"] is None
    assert draft["public_id"]
    assert draft["captured_at"]  # defaulted to now when omitted


def test_capture_dedupes_same_notification_identity(client: TestClient, *, identity) -> None:
    first = capture_repayment_draft(client, identity, amount_cents=12345, notification_key='ident-abc')
    second = capture_repayment_draft(client, identity, amount_cents=12345, notification_key='ident-abc')
    # Same per-post identity + content → the existing draft, not a twin.
    assert second["public_id"] == first["public_id"]
    listing = client.get("/api/repayment-drafts", headers=identity.app_headers).json()
    assert sum(1 for d in listing["items"] if d["public_id"] == first["public_id"]) == 1
    # The same original is also reserved across types, including older clients.
    wrong_type = client.post("/api/expenses/notification-drafts", headers=identity.app_headers,
        json={"source": "alipay", "amount_cents": 12345, "notification_key": "ident-abc"})
    assert wrong_type.status_code == 409, wrong_type.text


@pytest.mark.parametrize("confirmed", [False, True])
def test_wrong_repayment_becomes_one_reviewable_expense_and_old_capture_cannot_return(client, identity, monkeypatch, confirmed):
    from app.models import Expense, PaymentCapture
    from app.services import payment_capture_commands
    key = "real-notification-redacted"
    draft = capture_repayment_draft(client, identity, amount_cents=3790, notification_key=key)
    url = f"/api/repayment-drafts/{draft['public_id']}/as-expense"
    body = {"reason": "花呗消费，末尾只是还款提醒", "notification_key": key}
    if confirmed:
        debt = _create_external_debt(client, identity, counterparty_label="卡一")
        _create_external_debt(client, identity, counterparty_label="卡二")
        _confirm_draft_to_debt(client, identity, draft_public_id=draft["public_id"], debt=debt)
        current = client.get(f"/api/repayment-drafts/{draft['public_id']}", headers=identity.app_headers).json()
        body["correction_versions"] = current["correction_versions"]
        next_draft = capture_repayment_draft(client, identity, amount_cents=3790, notification_key="next-notification")
        assert _listed(client, identity, public_id=next_draft["public_id"])["suggested_debt_public_id"] == debt["public_id"]
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    def fail_after_target(*args, **kwargs):
        raise RuntimeError("injected before atomic commit")
    with monkeypatch.context() as patch:
        patch.setattr(payment_capture_commands, "append_decision", fail_after_target)
        with pytest.raises(RuntimeError, match="before atomic commit"):
            client.post(url, headers=headers, json=body)
    assert client.get(f"/api/repayment-drafts/{draft['public_id']}", headers=identity.app_headers).json()["status"] == ("confirmed" if confirmed else "pending")
    with SessionLocal() as db:
        assert db.scalar(select(Expense).where(Expense.original_amount_minor == 3790)) is None
    first = client.post(url, headers=headers, json=body)
    assert first.status_code == 200, first.text
    receipt = first.json()
    again = client.post(url, headers=headers, json=body)
    assert again.json() == receipt
    new_key = client.post(url, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json=body)
    assert new_key.json()["expense_public_id"] == receipt["expense_public_id"]
    expense = client.get(f"/api/expenses/{receipt['expense_id']}", headers=identity.app_headers).json()
    assert expense["status"] == "pending" and expense["original_amount_minor"] == 3790
    corrected = client.get(f"/api/repayment-drafts/{draft['public_id']}", headers=identity.app_headers).json()
    assert corrected["corrected_expense_id"] == receipt["expense_id"]
    if confirmed:
        assert corrected["status"] == "confirmed"  # The original accepted receipt remains historical evidence.
        assert client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()["remaining_amount_cents"] == 50000
        assert _listed(client, identity, public_id=next_draft["public_id"])["suggested_debt_public_id"] is None
    else:
        assert corrected["status"] == "dismissed"
    replay = client.post("/api/payment-captures", headers=identity.app_headers, json={
        "notification_key": key, "source": "alipay", "captured_at": draft["captured_at"],
        "original_currency": "CNY", "original_amount_minor": 3790, "merchant": "花呗",
        "suggested_kind": "repayment", "parser_version": "legacy", "candidates": []})
    assert replay.status_code == 201, replay.text
    assert replay.json()["kind"] == "expense" and replay.json()["expense_id"] == receipt["expense_id"]
    with SessionLocal() as db:
        capture = db.scalar(select(PaymentCapture).where(PaymentCapture.public_id == receipt["public_id"]))
        assert len(capture.decisions) == 1 and capture.decisions[0]["reason"] == body["reason"]


def test_uncertain_payment_survives_until_explicit_review_without_financial_fact(client, identity):
    body = {"notification_key": "ambiguous-original", "source": "alipay", "captured_at": "2026-10-17T05:13:19Z",
        "original_currency": "CNY", "suggested_kind": "review", "parser_version": "transaction-evidence-v2",
        "candidates": [{"kind": "expense", "amount_minor": 3790, "field": "text", "evidence": "amount_bound_expense"},
            {"kind": "repayment", "amount_minor": 50000, "field": "bigText", "evidence": "amount_bound_repayment"}]}
    captured = client.post("/api/payment-captures", headers=identity.app_headers, json=body)
    assert captured.status_code == 201, captured.text
    row = captured.json()
    assert row["expense_id"] is None and row["repayment_public_id"] is None
    assert row in client.get("/api/payment-captures", headers=identity.app_headers).json()
    decision = {"expected_row_version": row["row_version"], "kind": "expense", "original_currency": "CNY",
        "original_amount_minor": 3790, "reason": "已核对原支付记录"}
    url = f"/api/payment-captures/{row['public_id']}/decision"
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    chosen = client.post(url, headers=headers, json=decision)
    assert chosen.status_code == 200, chosen.text
    assert client.post(url, headers=headers, json=decision).json() == chosen.json()
    assert client.post(url, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json=decision).status_code == 409
    expense = client.get(f"/api/expenses/{chosen.json()['expense_id']}", headers=identity.app_headers).json()
    assert expense["status"] == "pending" and expense["expense_time"] is None
    assert expense["accounting_time"]["precision"] == "unknown"


def test_capture_distinct_identities_same_content_create_two(
    client: TestClient, *, identity
) -> None:
    first = capture_repayment_draft(client, identity, amount_cents=9900, notification_key='ident-1')
    second = capture_repayment_draft(client, identity, amount_cents=9900, notification_key='ident-2')
    # Two genuinely distinct posts (same咖啡 twice) → two reviewable drafts (codex PR#20).
    assert second["public_id"] != first["public_id"]


def test_capture_invalid_source_is_422(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/repayment-drafts",
        headers=identity.app_headers,
        json={"source": "venmo", "amount_cents": 1000},
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "notification_source_invalid"


def test_capture_viewer_is_403(client: TestClient, *, identity) -> None:
    set_owner_ledger_role("viewer")
    response = client.post(
        "/api/repayment-drafts",
        headers=identity.app_headers,
        json={"source": "alipay", "amount_cents": 1000},
    )
    assert response.status_code == 403, response.json()
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_capture_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/repayment-drafts",
        json={"source": "alipay", "amount_cents": 1000},
    )
    assert response.status_code == 401


# --- list -----------------------------------------------------------------------


def test_list_returns_pending_and_filters_by_status(client: TestClient, *, identity) -> None:
    draft = capture_repayment_draft(client, identity, notification_key='list-1')
    pending = client.get("/api/repayment-drafts", headers=identity.app_headers).json()
    assert any(d["public_id"] == draft["public_id"] for d in pending["items"])
    # A status that no draft holds yet returns an empty inbox.
    confirmed = client.get(
        "/api/repayment-drafts?status=confirmed", headers=identity.app_headers
    ).json()
    assert all(d["public_id"] != draft["public_id"] for d in confirmed["items"])


# --- list: §杠杆③ slice 3b server-suggested target Debt --------------------------


def _create_external_debt(
    client: TestClient,
    identity,
    *,
    counterparty_label: str,
    principal_amount_cents: int = 50000,
) -> dict:
    response = client.post(
        "/api/debts",
        headers=negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())}),
        json={
            "home_currency_code": "CNY", "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": counterparty_label,
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _create_confirmed_expense(
    client: TestClient,
    identity,
    *,
    merchant: str = "京东",
    category: str = "白条",
    amount_cents: int = 391363,
    time_input: dict | None = None,
) -> dict:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "client_ref": str(uuid4()),
            "home_currency_code": "CNY", "amount_cents": amount_cents,
            "merchant": merchant,
            "category": category,
            **({"time_input": time_input} if time_input else {"expense_time": "2026-06-28T13:13:00Z"}),
        },
    )
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "confirmed"
    return response.json()


def _confirm_draft_to_debt(
    client: TestClient,
    identity,
    *,
    draft_public_id: str,
    debt: dict,
) -> dict:
    response = client.post(
        f"/api/repayment-drafts/{draft_public_id}/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "target_debt_public_id": debt["public_id"],
            "expected_row_version": debt["row_version"],
            "target_choice_explicit": True,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _listed(client: TestClient, identity, *, public_id: str, status: str = "pending") -> dict:
    listing = client.get(
        f"/api/repayment-drafts?status={status}", headers=identity.app_headers
    ).json()
    match = next((d for d in listing["items"] if d["public_id"] == public_id), None)
    assert match is not None, listing
    return match


def test_list_pending_draft_carries_server_suggestion(client: TestClient, *, identity) -> None:
    # An open external/manual Debt labeled the same as the captured platform → the inbox list
    # pre-selects it via suggested_debt_public_id (ephemeral — computed in the list path).
    debt = _create_external_debt(client, identity, counterparty_label="花呗")
    draft = capture_repayment_draft(client, identity, merchant_label='花呗', amount_cents=20000)
    listed = _listed(client, identity, public_id=draft["public_id"])
    assert listed["suggested_debt_public_id"] == debt["public_id"]



def test_confirmed_expense_can_enter_repayment_draft_model(
    client: TestClient, *, identity, monkeypatch
) -> None:
    debt = _create_external_debt(
        client,
        identity,
        counterparty_label="京东白条",
        principal_amount_cents=500000,
    )
    calendar = client.get("/api/ledgers/owner/calendar", headers=identity.app_headers).json()
    original_time = {"precision": "date_only", "calendar_revision": calendar["revision"],
        "user_local_date": "2026-04-30", "accounting_date": "2026-05-01"}
    expense = _create_confirmed_expense(client, identity, merchant="京东", category="白条", time_input=original_time)

    response = client.post(
        f"/api/expenses/{expense['id']}/repayment-draft",
        headers=identity.app_headers,
        json={"expected_row_version": expense["row_version"]},
    )
    assert response.status_code == 201, response.json()
    draft = response.json()
    assert draft["status"] == "pending"
    assert draft["source"] == "other"
    assert draft["amount_cents"] == expense["amount_cents"]
    assert draft["merchant_label"] == "京东"

    listed = _listed(client, identity, public_id=draft["public_id"])
    assert listed["suggested_debt_public_id"] == debt["public_id"]

    assert draft["source_expense_public_id"] == expense["public_id"]
    # Delayed review after a ledger-calendar change keeps the captured date, without
    # reconstructing the transaction owner in a MagicMock-based second product.
    changed_calendar = client.post("/api/ledgers/owner/calendar", headers=negotiated_headers(client,
        {**identity.app_headers, "Idempotency-Key": str(uuid4())}),
        json={"timezone_name": "Pacific/Honolulu", "expected_revision": calendar["revision"]})
    assert changed_calendar.status_code == 200, changed_calendar.text
    from app.models import Expense, ExpenseOffsetFact, Repayment
    from app.services.expense_offset_summary import expense_financial_summary

    confirm_url = f"/api/repayment-drafts/{draft['public_id']}/confirm"
    body = {"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]}
    rejected = client.post(confirm_url, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={**body, "original_currency": "CNY", "original_amount": "6000.00"})
    assert rejected.status_code == 422, rejected.json()
    with SessionLocal() as db:
        assert not db.scalars(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id == expense["id"])).all()
        assert db.get(Expense, expense["id"]).row_version == expense["row_version"]

    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    saved = client.post(confirm_url, headers=headers, json=body)
    assert saved.status_code == 201, saved.json()
    replay = client.post(confirm_url, headers=headers, json=body)
    assert replay.status_code == 201 and replay.json() == saved.json()
    with SessionLocal() as db:
        original = db.get(Expense, expense["id"])
        offsets = list(db.scalars(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id == original.id)))
        assert original.status == "confirmed" and original.amount_cents == expense["amount_cents"]
        assert len(offsets) == 1 and offsets[0].kind == "reversal"
        assert offsets[0].accounting_date == original.accounting_date
        assert expense_financial_summary(original, offsets).lineage_home_net_cents == 0
        payments = db.scalars(select(Repayment).where(Repayment.debt_id == db.scalar(select(Debt.id)
            .where(Debt.public_id == debt["public_id"])))).all()
        assert len(payments) == 1
        assert payments[0].paid_at is None
        assert payments[0].accounting_time_snapshot["user_local_date"] == "2026-04-30"
        assert payments[0].accounting_time_snapshot["accounting_date"] == "2026-05-01"
        assert payments[0].accounting_time_snapshot["calendar_revision"] == calendar["revision"]

    # Reverse the wrong confirmation through the same actual command. Its offset
    # restoration must share the transaction, including a failure after both writes.
    from app.models import RepaymentVoid
    from app.services import payment_capture_commands
    correction_url = f"/api/repayment-drafts/{draft['public_id']}/as-expense"
    current = client.get(f"/api/repayment-drafts/{draft['public_id']}", headers=identity.app_headers).json()
    correction = {"reason": "已核对原单，这是消费", "correction_versions": current["correction_versions"]}
    correction_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    def fail_before_receipt(*args, **kwargs):
        raise RuntimeError("restore before receipt")
    with monkeypatch.context() as patch:
        patch.setattr(payment_capture_commands, "append_decision", fail_before_receipt)
        with pytest.raises(RuntimeError, match="restore before receipt"):
            client.post(correction_url, headers=correction_headers, json=correction)
    with SessionLocal() as db:
        assert db.scalar(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id == expense["id"])).status == "active"
        assert db.scalar(select(RepaymentVoid.id)) is None
    restored = client.post(correction_url, headers=correction_headers, json=correction)
    assert restored.status_code == 200, restored.text
    assert restored.json()["expense_id"] == expense["id"]
    assert client.post(correction_url, headers=correction_headers, json=correction).json() == restored.json()
    assert client.post(confirm_url, headers=headers, json=body).json() == saved.json()
    with SessionLocal() as db:
        original = db.get(Expense, expense["id"])
        offsets = list(db.scalars(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id == original.id)))
        assert offsets[0].status == "voided"
        assert expense_financial_summary(original, [row for row in offsets if row.status == "active"]).lineage_home_net_cents == original.amount_cents
        assert db.scalar(select(RepaymentVoid.id)) is not None


def test_expense_repayment_draft_dedupes_same_expense(
    client: TestClient, *, identity
) -> None:
    expense = _create_confirmed_expense(client, identity)
    payload = {"expected_row_version": expense["row_version"]}

    first = client.post(
        f"/api/expenses/{expense['id']}/repayment-draft",
        headers=identity.app_headers,
        json=payload,
    )
    assert first.status_code == 201, first.json()
    second = client.post(
        f"/api/expenses/{expense['id']}/repayment-draft",
        headers=identity.app_headers,
        json=payload,
    )
    assert second.status_code == 201, second.json()
    assert second.json()["public_id"] == first.json()["public_id"]

    listing = client.get("/api/repayment-drafts", headers=identity.app_headers).json()
    assert sum(1 for d in listing["items"] if d["public_id"] == first.json()["public_id"]) == 1
    dismissed = client.post(f"/api/repayment-drafts/{first.json()['public_id']}/dismiss",
        headers=identity.app_headers, json={})
    assert dismissed.status_code == 201
    from app.models import Expense, ExpenseOffsetFact
    with SessionLocal() as db:
        assert db.get(Expense, expense["id"]).row_version == expense["row_version"]
        assert not db.scalars(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id == expense["id"])).all()


def test_expense_repayment_draft_uses_existing_learning(
    client: TestClient, *, identity
) -> None:
    learned_target = _create_external_debt(client, identity, counterparty_label="招商卡")
    _create_external_debt(client, identity, counterparty_label="浦发卡")
    learned = capture_repayment_draft(client, identity, source='other', merchant_label='账单还款', amount_cents=1000, notification_key='learn-expense-bridge')
    _confirm_draft_to_debt(
        client,
        identity,
        draft_public_id=learned["public_id"],
        debt=learned_target,
    )
    expense = _create_confirmed_expense(
        client,
        identity,
        merchant="账单还款",
        category="其他",
        amount_cents=1000,
    )

    created = client.post(
        f"/api/expenses/{expense['id']}/repayment-draft",
        headers=identity.app_headers,
        json={"expected_row_version": expense["row_version"]},
    )
    assert created.status_code == 201, created.json()

    listed = _listed(client, identity, public_id=created.json()["public_id"])
    assert listed["suggested_debt_public_id"] == learned_target["public_id"]


def test_expense_repayment_draft_rejects_stale_expense_snapshot(
    client: TestClient, *, identity
) -> None:
    expense = _create_confirmed_expense(client, identity)
    response = client.post(
        f"/api/expenses/{expense['id']}/repayment-draft",
        headers=identity.app_headers,
        json={"expected_row_version": expense["row_version"] + 1},
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "state_conflict"
    draft = client.post(f"/api/expenses/{expense['id']}/repayment-draft", headers=identity.app_headers,
        json={"expected_row_version": expense["row_version"]}).json()
    edited = client.post(f"/api/expenses/{expense['id']}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": expense["row_version"], "reason": "核对商家", "merchant": "真实商家"})
    assert edited.status_code == 201, edited.json()
    debt = _create_external_debt(client, identity, counterparty_label="京东白条", principal_amount_cents=500000)
    refused = client.post(f"/api/repayment-drafts/{draft['public_id']}/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]})
    assert refused.status_code == 409 and refused.json()["error"] == "state_conflict"
    from app.models import ExpenseOffsetFact, Repayment
    with SessionLocal() as db:
        assert not db.scalars(select(ExpenseOffsetFact)).all()
        assert not db.scalars(select(Repayment)).all()
    reviewed = client.post(f"/api/expenses/{expense['id']}/repayment-draft", headers=identity.app_headers,
        json={"expected_row_version": edited.json()["expense"]["row_version"]})
    assert reviewed.status_code == 201 and reviewed.json()["public_id"] != draft["public_id"]
    _confirm_draft_to_debt(client, identity, draft_public_id=reviewed.json()["public_id"], debt=debt)


def test_list_suggestion_absent_when_ambiguous(client: TestClient, *, identity) -> None:
    # Two open Debt both labeled 花呗 both feasible → the match is ambiguous → no suggestion
    # (the user picks). Exercises the real candidate query returning >1 plus the matcher tie.
    _create_external_debt(client, identity, counterparty_label="花呗")
    _create_external_debt(client, identity, counterparty_label="花呗")
    draft = capture_repayment_draft(client, identity, merchant_label='花呗', amount_cents=10000)
    listed = _listed(client, identity, public_id=draft["public_id"])
    assert listed["suggested_debt_public_id"] is None


def test_list_suggestion_only_for_pending_not_resolved(client: TestClient, *, identity) -> None:
    # The suggestion is for the review action; once a draft is resolved it carries none, even
    # though the candidate Debt still exists.
    _create_external_debt(client, identity, counterparty_label="花呗")
    draft = capture_repayment_draft(client, identity, merchant_label='花呗', amount_cents=10000)
    # Pending → suggestion present.
    assert _listed(client, identity, public_id=draft["public_id"])["suggested_debt_public_id"]
    dismiss = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=identity.app_headers, json={}
    )
    assert dismiss.status_code == 201, dismiss.json()
    resolved = _listed(client, identity, public_id=draft["public_id"], status="dismissed")
    assert resolved["suggested_debt_public_id"] is None


def test_service_unfiltered_list_suggests_only_pending_drafts(client: TestClient, *, identity) -> None:
    # The route always filters by ONE status (default pending), so a pending-only list never
    # co-lists a resolved draft — the per-draft `status == "pending"` guard only bites on a
    # status=None mixed list (e.g. a future all-statuses view), reachable at the service level.
    # Pin it there: a pending AND a dismissed draft that BOTH match the same Debt → only the
    # pending one carries the suggestion. (Mutation: drop the per-draft pending guard → the
    # dismissed draft, co-listed while has_pending=True keeps candidates non-empty, also gets one.)
    debt = _create_external_debt(client, identity, counterparty_label="花呗")
    pending = capture_repayment_draft(client, identity, merchant_label='花呗', amount_cents=20000, notification_key='mix-pending')
    resolved = capture_repayment_draft(client, identity, merchant_label='花呗', amount_cents=20000, notification_key='mix-dismissed')
    dismiss = client.post(
        f"/api/repayment-drafts/{resolved['public_id']}/dismiss", headers=identity.app_headers, json={}
    )
    assert dismiss.status_code == 201, dismiss.json()

    with SessionLocal() as db:
        owner_account_id = db.scalar(select(Account.id).order_by(Account.id.asc()).limit(1))
        listing = debt_service.list_repayment_drafts(
            db, tenant_id="owner", actor_account_id=owner_account_id, status=None
        )
    by_id = {item.public_id: item for item in listing.items}
    assert by_id[pending["public_id"]].suggested_debt_public_id == debt["public_id"]
    assert by_id[resolved["public_id"]].suggested_debt_public_id is None


def _seed_debt_orm(
    *,
    counterparty_type: str,
    source_type: str,
    status: str,
    label: str = "花呗",
    principal_amount_cents: int = 50000,
) -> str:
    """ORM-seed a tenant 'owner' Debt of an arbitrary shape (bypasses the create-path guards so the
    candidate query's WHERE-clause exclusions can be exercised directly)."""
    with SessionLocal() as db:
        owner = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
        assert owner is not None
        # Keep each seeded shape STRUCTURALLY valid (ck_debts_member_has_account /
        # ck_debts_bill_split_has_source_id) while still representing the excluded
        # category: a member counterparty needs an internal account; a bill_split
        # Debt needs a source_id. (manual → source_id stays NULL.)
        counterparty_account_id = None
        if counterparty_type == "member":
            member = Account(display_name="家人")
            db.add(member)
            db.flush()
            counterparty_account_id = member.id
        source_id = str(uuid4()) if source_type == "bill_split" else None
        now = now_utc()
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner.id,
            created_by_account_id=owner.id,
            direction="i_owe",
            counterparty_type=counterparty_type,
            counterparty_account_id=counterparty_account_id,
            counterparty_label=label,
            principal_amount_cents=principal_amount_cents,
            home_currency_code="CNY",
            status=status,
            source_type=source_type,
            source_id=source_id,
            created_at=now,
            updated_at=now,
        )
        db.add(debt)
        db.commit()
        return debt.public_id


def test_list_suggestion_excludes_non_repayable_debt_shapes(client: TestClient, *, identity) -> None:
    # The candidate query keeps the suggestion to a repayable target (open + external + manual),
    # mirroring guard_direct_fact_writable / the Android isRepayableDebt. Seed each excluded shape
    # as the ONLY 花呗 Debt — a dropped WHERE clause would make exactly one a candidate and surface
    # a non-repayable suggestion. With all filters intact the 花呗 draft has no confident match.
    _seed_debt_orm(counterparty_type="external", source_type="manual", status="voided")  # bites status!='voided'
    _seed_debt_orm(counterparty_type="member", source_type="manual", status="open")  # bites counterparty='external'
    _seed_debt_orm(counterparty_type="external", source_type="bill_split", status="open")  # bites source='manual'
    draft = capture_repayment_draft(client, identity, merchant_label='花呗', amount_cents=20000)
    listed = _listed(client, identity, public_id=draft["public_id"])
    assert listed["suggested_debt_public_id"] is None


# --- dismiss --------------------------------------------------------------------


def test_dismiss_is_idempotent_when_already_dismissed(
    client: TestClient, monkeypatch, *, identity
) -> None:
    draft = capture_repayment_draft(client, identity, amount_cents=4200)
    first = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=identity.app_headers, json={}
    )
    assert first.status_code == 201, first.json()
    assert first.json()["status"] == "dismissed"
    assert first.json()["resolved_at"]
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        again = client.post(
            f"/api/repayment-drafts/{draft['public_id']}/dismiss",
            headers=identity.app_headers,
            json={},
        )
        assert again.status_code == 201, again.json()
        assert again.json() == first.json()
    finally:
        get_settings.cache_clear()


def test_dismiss_viewer_is_403(client: TestClient, *, identity) -> None:
    # dismiss is a writers-only destructive op; its get_current_writer_context dep is
    # per-handler, so it needs its own viewer-403 pin (capture/confirm cover their handlers).
    draft = capture_repayment_draft(client, identity, amount_cents=1000)
    set_owner_ledger_role("viewer")
    response = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=identity.app_headers, json={}
    )
    assert response.status_code == 403, response.json()
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_dismiss_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    draft = capture_repayment_draft(client, identity, amount_cents=1000)
    response = client.post(f"/api/repayment-drafts/{draft['public_id']}/dismiss", json={})
    assert response.status_code == 401
