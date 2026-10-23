"""Repayment memory requires an explicit, current personal choice and stays reversible.

The deterministic matcher remains first. Memory never changes financial facts,
crosses actors, resolves conflicting choices, or revives withdrawn feedback.
"""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, AlgorithmDecision, Debt, LedgerLearningEvent, RepaymentDraft
from app.services import debt_service
from app.services.time_service import now_utc
from tests._runtime_protocol import negotiated_headers

# A merchant label that confidently matches NO debt label below ("卡A"/"卡B"/...), so the
# confident matcher returns None and the learned fallback is what drives the suggestion.
_NO_MATCH_LABEL = "还款收据"


@pytest.fixture
def local_client(client, monkeypatch):
    from app.main import app
    from app.routes.owner_console import _require_local

    monkeypatch.setitem(app.dependency_overrides, _require_local, lambda: None)
    return client


def test_legacy_confirmation_without_explicit_target_choice_does_not_train(client, identity):
    debt = _create_external_debt(client, identity, counterparty_label="卡A")
    first = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="legacy-first")
    response = client.post(f"/api/repayment-drafts/{first['public_id']}/confirm", headers=_idem(identity.app_headers),
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]})
    assert response.status_code == 201 and response.json()["status"] == "confirmed"
    second = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="legacy-next")
    assert _suggestion(client, identity, second["public_id"]) is None


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _create_external_debt(
    client: TestClient, identity, *, counterparty_label: str, principal_amount_cents: int = 50000
) -> dict:
    response = client.post(
        "/api/debts",
        headers=negotiated_headers(client, _idem(identity.app_headers)),
        json={
            "home_currency_code": "CNY", "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": counterparty_label,
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _create_draft(
    client: TestClient,
    identity,
    *,
    merchant_label: str,
    source: str = "alipay",
    amount_cents: int = 20000,
    notification_key: str,
) -> dict:
    response = client.post(
        "/api/repayment-drafts",
        headers=identity.app_headers,
        json={
            "source": source,
            "amount_cents": amount_cents,
            "merchant_label": merchant_label,
            "notification_key": notification_key,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _confirm(client: TestClient, identity, draft_public_id: str, debt: dict) -> dict:
    """Confirm a pending draft against ``debt``; returns the fold-after DebtResponse."""
    response = client.post(
        f"/api/repayment-drafts/{draft_public_id}/confirm",
        headers=_idem(identity.app_headers),
        json={
            "target_debt_public_id": debt["public_id"],
            "expected_row_version": debt["row_version"],
            "target_choice_explicit": True,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _repay(client: TestClient, identity, public_id: str, *, amount_cents: int, row_version: int) -> dict:
    response = client.post(
        f"/api/debts/{public_id}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": amount_cents, "expected_row_version": row_version},
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _suggestion(client: TestClient, identity, draft_public_id: str) -> str | None:
    listing = client.get(
        "/api/repayment-drafts?status=pending", headers=identity.app_headers
    ).json()
    match = next((d for d in listing["items"] if d["public_id"] == draft_public_id), None)
    assert match is not None, listing
    return match["suggested_debt_public_id"]


def _seed_account(display_name: str) -> int:
    with SessionLocal() as db:
        account = Account(display_name=display_name)
        db.add(account)
        db.commit()
        return account.id


def _seed_pending_draft(
    *, tenant_id: str, account_id: int, merchant_label: str, source: str = "alipay", amount_cents: int = 20000
) -> str:
    """ORM-seed a PENDING draft created by ``account_id`` (used to place a draft under a DIFFERENT
    account in the same ledger — the API would key created_by off the caller)."""
    with SessionLocal() as db:
        draft = RepaymentDraft(
            tenant_id=tenant_id,
            created_by_account_id=account_id,
            source=source,
            amount_cents=amount_cents,
            home_currency_code="CNY",
            merchant_label=merchant_label,
            captured_at=now_utc(),
            draft_idempotency_key=str(uuid4()),
            status="pending",
            created_at=now_utc(),
        )
        db.add(draft)
        db.commit()
        return draft.public_id


def test_learns_target_from_prior_confirmation(client: TestClient, *, identity) -> None:
    # Two repayable Debts; the captured label matches NEITHER (confident matcher → None). The
    # account has previously confirmed this exact signature to X → the learned fallback pre-selects
    # X (not Y). (Mutation: drop the learned fallback → no suggestion.)
    x = _create_external_debt(client, identity, counterparty_label="卡A")
    _create_external_debt(client, identity, counterparty_label="卡B")
    prior = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="learn-1")
    _confirm(client, identity, prior["public_id"], x)

    fresh = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="learn-2")
    assert _suggestion(client, identity, fresh["public_id"]) == x["public_id"]


def test_ambiguous_signature_history_suppresses(client: TestClient, *, identity) -> None:
    # The same signature has been confirmed to TWO distinct still-feasible Debts (a generic label
    # split across cards) → the learned fallback stays silent rather than guess the wrong card.
    x = _create_external_debt(client, identity, counterparty_label="卡A")
    y = _create_external_debt(client, identity, counterparty_label="卡B")
    to_x = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="amb-x")
    _confirm(client, identity, to_x["public_id"], x)
    to_y = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="amb-y")
    _confirm(client, identity, to_y["public_id"], y)

    fresh = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="amb-new")
    assert _suggestion(client, identity, fresh["public_id"]) is None


def test_stale_learned_debt_not_suggested(client: TestClient, *, identity) -> None:
    # The account confirmed this signature to X, but X is since fully repaid (cleared → infeasible);
    # a still-open Y exists but was never confirmed for this signature → no suggestion (the learned
    # debt must still be in the feasible candidate set). (Mutation: drop the feasibility filter →
    # the cleared X gets re-suggested.)
    x = _create_external_debt(client, identity, counterparty_label="卡A")  # principal 50000
    _create_external_debt(client, identity, counterparty_label="卡B")  # stays open, never confirmed
    prior = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="stale-1")
    _confirm(client, identity, prior["public_id"], x)  # records a 20000 repayment on X
    # Clear X entirely → remaining 0 → no longer a repayable candidate. (Confirm returns the
    # draft, not the Debt, so re-read X for its current row_version + remaining.)
    refreshed = client.get(f"/api/debts/{x['public_id']}", headers=identity.app_headers).json()
    cleared = _repay(
        client,
        identity,
        x["public_id"],
        amount_cents=refreshed["remaining_amount_cents"],
        row_version=refreshed["row_version"],
    )
    assert cleared["status"] == "cleared"

    fresh = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="stale-2")
    assert _suggestion(client, identity, fresh["public_id"]) is None


def test_learning_is_account_scoped(client: TestClient, *, identity) -> None:
    # The owner confirmed this signature to X. A DIFFERENT account's pending draft in the SAME
    # ledger with the same signature must NOT inherit the owner's learned target — repayment
    # capture is personal. (Mutation: scope the history query to tenant instead of account →
    # the other account's draft would also pre-select X.)
    x = _create_external_debt(client, identity, counterparty_label="卡A")
    owner_prior = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="acct-own")
    _confirm(client, identity, owner_prior["public_id"], x)

    # Positive control: the owner's own fresh draft DOES inherit the learned target.
    owner_fresh = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="acct-own2")
    assert _suggestion(client, identity, owner_fresh["public_id"]) == x["public_id"]

    # A second account's pending draft (same ledger, same signature) gets no suggestion. The
    # inbox is account-scoped (privacy), so this draft NEVER appears in the owner's API list at
    # all — read it at the service layer AS the second account (mirrors test_repayment_drafts.py's
    # direct list call): it shows in its own owner's list and inherits NO learned target. (Mutation:
    # scope the history query to tenant instead of account → the second account would pre-select X.)
    other_account_id = _seed_account("家人B")
    other_draft_id = _seed_pending_draft(
        tenant_id="owner", account_id=other_account_id, merchant_label=_NO_MATCH_LABEL
    )
    with SessionLocal() as db:
        other_listing = debt_service.list_repayment_drafts(
            db, tenant_id="owner", actor_account_id=other_account_id, status="pending"
        )
    other = next((d for d in other_listing.items if d.public_id == other_draft_id), None)
    assert other is not None, "the second account sees its own capture"
    assert other.suggested_debt_public_id is None, "but it inherits no learned target from the owner"


def test_learns_blank_label_signature(client: TestClient, *, identity) -> None:
    # Blank captured label (the parser anchored no platform): the confident matcher returns None
    # whenever ≥2 Debts are feasible (it only suggests a lone feasible target for a blank label),
    # so the learned fallback drives it. A consistently-confirmed blank-(alipay) signature still
    # learns its target — target=normalize(None)="" matches the prior blank-label confirms.
    x = _create_external_debt(client, identity, counterparty_label="卡A")
    _create_external_debt(client, identity, counterparty_label="卡B")  # 2 feasible → matcher silent
    prior = _create_draft(client, identity, merchant_label=None, notification_key="blank-1")
    _confirm(client, identity, prior["public_id"], x)

    fresh = _create_draft(client, identity, merchant_label=None, notification_key="blank-2")
    assert _suggestion(client, identity, fresh["public_id"]) == x["public_id"]


def test_confident_match_wins_over_learned_history(client: TestClient, *, identity) -> None:
    # The confident label match always beats the learned habit: even though the account once
    # confirmed this label to Y, a fresh capture whose label exactly matches X is suggested X.
    # (Mutation: check history before the confident matcher → it would return Y.)
    x = _create_external_debt(client, identity, counterparty_label="招商信用卡")
    y = _create_external_debt(client, identity, counterparty_label="工商卡")
    prior = _create_draft(client, identity, merchant_label="招商信用卡", notification_key="conf-1")
    _confirm(client, identity, prior["public_id"], y)  # learned habit points at Y

    fresh = _create_draft(client, identity, merchant_label="招商信用卡", notification_key="conf-2")
    assert _suggestion(client, identity, fresh["public_id"]) == x["public_id"]


def test_owner_repayment_axes_preserve_facts_and_withdrawal_survives_cleanup(local_client, identity):
    from app.services.learning_service._algorithm_registry import REPAYMENT_CHOICE
    from app.services.learning_service._cleanup import cleanup_expired_learning_events

    client = local_client
    debt = _create_external_debt(client, identity, counterparty_label="卡A")
    prior = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="policy-prior")
    _confirm(client, identity, prior["public_id"], debt)
    first = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="policy-shown")
    assert _suggestion(client, identity, first["public_id"]) == debt["public_id"]
    policy = {"ledger_id": "owner", "decision_type": REPAYMENT_CHOICE.decision_type,
        "algorithm_version": REPAYMENT_CHOICE.current_version}
    facts = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    page = client.get("/owner/algorithm-versions?ledger_id=owner")
    assert page.status_code == 200 and "明确选择了对应欠款" in page.text and "当时选择：卡A" in page.text
    assert client.post("/owner/algorithm-versions/policy", data={**policy,
        "axis": "new_suggestions", "enabled": "false"}).status_code == 200
    second = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="policy-new")
    assert _suggestion(client, identity, first["public_id"]) == debt["public_id"]
    assert _suggestion(client, identity, second["public_id"]) is None
    assert client.post("/owner/algorithm-versions/withdraw", data=policy).status_code == 200
    assert client.post("/owner/algorithm-versions/policy", data={**policy,
        "axis": "new_suggestions", "enabled": "true"}).status_code == 200
    assert _suggestion(client, identity, first["public_id"]) is None
    assert _suggestion(client, identity, second["public_id"]) == debt["public_id"]
    with SessionLocal() as db:
        event = db.query(LedgerLearningEvent).filter_by(signal_type="repayment_choice", event_type="manual_override").one()
        event_id, payload = event.public_id, event.after_payload
    assert client.post("/owner/algorithm-versions/withdraw-feedback", data={
        "ledger_id": "owner", "event_public_id": event_id}).status_code == 200
    with SessionLocal() as db:
        cleanup_expired_learning_events(db, tenant_id="owner", now=now_utc() + timedelta(days=800))
        assert db.query(LedgerLearningEvent).filter_by(public_id=event_id).one().after_payload == payload
        tombstone = db.query(LedgerLearningEvent).filter_by(event_type="withdraw").one()
        assert tombstone.actor_account_id is None and tombstone.retention_days == 0
    assert _suggestion(client, identity, second["public_id"]) is None
    assert client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json() == facts


def test_repayment_training_quarantine_and_replay_do_not_change_financial_result(local_client, identity):
    from app.services.learning_service._algorithm_registry import REPAYMENT_CHOICE

    client = local_client
    debt = _create_external_debt(client, identity, counterparty_label="卡A")
    prior = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="replay-prior")
    headers = _idem(identity.app_headers)
    body = {"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"], "target_choice_explicit": True}
    url = f"/api/repayment-drafts/{prior['public_id']}/confirm"
    saved = client.post(url, headers=headers, json=body)
    assert saved.status_code == 201 and client.post(url, headers=headers, json=body).json() == saved.json()
    with SessionLocal() as db:
        assert db.query(LedgerLearningEvent).filter_by(signal_type="repayment_choice").count() == 1
    pending = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="training-new")
    policy = {"ledger_id": "owner", "decision_type": REPAYMENT_CHOICE.decision_type,
        "algorithm_version": REPAYMENT_CHOICE.current_version, "axis": "training"}
    assert client.post("/owner/algorithm-versions/policy", data={**policy, "enabled": "false"}).status_code == 200
    assert _suggestion(client, identity, pending["public_id"]) is None
    assert client.post("/owner/algorithm-versions/policy", data={**policy, "enabled": "true"}).status_code == 200
    assert _suggestion(client, identity, pending["public_id"]) == debt["public_id"]
    current = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    _repay(client, identity, debt["public_id"], amount_cents=100, row_version=current["row_version"])
    assert _suggestion(client, identity, pending["public_id"]) == debt["public_id"], "ordinary balance changes do not invalidate target identity"


@pytest.mark.parametrize("changed", ["source", "target", "version"])
def test_repayment_memory_rechecks_both_sides_and_algorithm_version(client, identity, changed):
    debt = _create_external_debt(client, identity, counterparty_label="卡A")
    prior = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="changed-prior")
    _confirm(client, identity, prior["public_id"], debt)
    pending = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="changed-new")
    assert _suggestion(client, identity, pending["public_id"]) == debt["public_id"]
    with SessionLocal() as db:
        if changed == "source":
            db.query(RepaymentDraft).filter_by(public_id=prior["public_id"]).one().merchant_label = "其它原件"
        elif changed == "target":
            db.query(Debt).filter_by(public_id=debt["public_id"]).one().counterparty_label = "改判后的主体"
        else:
            event = db.query(LedgerLearningEvent).filter_by(signal_type="repayment_choice").one()
            event.after_payload = json.dumps({**json.loads(event.after_payload), "_algorithm_version": "future-version"})
        db.commit()
    assert _suggestion(client, identity, pending["public_id"]) is None


@pytest.mark.parametrize("action,expected", [("explicit", "accepted"), ("default", "dismissed"), ("dismiss", "dismissed")])
def test_finishing_repayment_closes_shown_advice_without_inventing_acceptance(client, identity, action, expected):
    debt = _create_external_debt(client, identity, counterparty_label="卡A", principal_amount_cents=100000)
    prior = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="finish-prior")
    _confirm(client, identity, prior["public_id"], debt)
    pending = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="finish-next")
    assert _suggestion(client, identity, pending["public_id"]) == debt["public_id"]
    if action == "dismiss":
        result = client.post(f"/api/repayment-drafts/{pending['public_id']}/dismiss", headers=identity.app_headers, json={})
    else:
        current = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
        result = client.post(f"/api/repayment-drafts/{pending['public_id']}/confirm", headers=_idem(identity.app_headers),
            json={"target_debt_public_id": debt["public_id"], "expected_row_version": current["row_version"],
                "target_choice_explicit": action == "explicit"})
    assert result.status_code in (200, 201), result.text
    with SessionLocal() as db:
        decision = db.query(AlgorithmDecision).filter_by(decision_type="repayment_choice").one()
        assert decision.status == expected
        events = list(db.query(LedgerLearningEvent).filter_by(signal_type="repayment_choice"))
        assert len(events) == (2 if action == "explicit" else 1)
        if action == "explicit":
            assert events[-1].decision_id == decision.id


@pytest.mark.parametrize("removed", [False, True])
def test_repayment_sweep_counts_and_closes_only_stale_subjects_in_its_ledger(client, identity, removed):
    from app.services.learning_service._lifecycle import stale_active_count, sweep_stale_active_decisions

    debt = _create_external_debt(client, identity, counterparty_label="卡A")
    prior = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="sweep-prior")
    _confirm(client, identity, prior["public_id"], debt)
    pending = _create_draft(client, identity, merchant_label=_NO_MATCH_LABEL, notification_key="sweep-next")
    assert _suggestion(client, identity, pending["public_id"]) == debt["public_id"]
    with SessionLocal() as db:
        assert stale_active_count(db, tenant_id="owner") == 0
        row = db.query(RepaymentDraft).filter_by(public_id=pending["public_id"]).one()
        if removed:
            db.delete(row)
        else:
            row.status = "dismissed"  # Simulate a restored historical terminal row missed by the original writer.
        db.flush()
        assert stale_active_count(db, tenant_id="owner") == 1
        assert sweep_stale_active_decisions(db, tenant_id="other-ledger") == 0
        assert sweep_stale_active_decisions(db, tenant_id="owner", batch_size=1) == 1
        assert stale_active_count(db, tenant_id="owner") == 0
        db.commit()
