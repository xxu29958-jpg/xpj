from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import AlgorithmDecision, LedgerLearningEvent
from tests._infra.assets import PNG_BYTES


def _confirmed(
    client: TestClient,
    *,
    identity,
    merchant: str,
    category: str,
    day: int,
) -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "client_ref": str(uuid4()),
            "home_currency_code": "CNY", "amount_cents": 1200 + day,
            "merchant": merchant,
            "category": category,
            "spent_at": (datetime.now(UTC) - timedelta(days=day)).isoformat(),
        },
    )
    assert response.status_code == 200, response.json()
    return int(response.json()["id"])


def _pending_notification(client: TestClient, *, identity, merchant: str) -> int:
    response = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json={
            "source": "alipay",
            "notification_key": str(uuid4()),
            "amount_cents": 1888,
            "merchant": merchant,
            "category": "其他",
            "spent_at": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200, response.json()
    return int(response.json()["id"])


@pytest.mark.parametrize("changed_side", ["subject", "candidate"])
@pytest.mark.parametrize("change", ["amount", "ignore", "reversal"])
def test_duplicate_feedback_freezes_both_sides_and_excludes_changed_evidence(client, identity, changed_side: str, change: str) -> None:
    from api_contract_helpers import confirm_expense_api, patch_expense

    from app.models import Expense
    from app.services.learning_service._source_eligibility import eligible_feedback

    candidate_id = _pending_notification(client, identity=identity, merchant="Pair evidence shop")
    subject_id = _pending_notification(client, identity=identity, merchant="Pair evidence shop")
    detail = client.get(f"/api/expenses/{subject_id}", headers=identity.app_headers).json()
    suggestion = next(row for row in detail["duplicate_candidates"] if row["candidate_id"] == candidate_id)
    response = client.post(f"/api/expenses/{subject_id}/suggestions/{suggestion['decision_public_id']}/reject",
        headers=identity.app_headers)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        event = db.query(LedgerLearningEvent).filter_by(subject_id=subject_id).one()
        event_id, original_payload = event.id, event.after_payload
        payload = json.loads(original_payload)
        assert payload["_candidate_context"]["public_id"] == db.get(Expense, candidate_id).public_id
        assert payload["_candidate_context"]["row_version"] == db.get(Expense, candidate_id).row_version
        assert payload["_source_context"]["row_version"] == db.get(Expense, subject_id).row_version
        assert eligible_feedback(db, tenant_id="owner", events=[event], actor_account_id=event.actor_account_id) == [event]
    changed_id = subject_id if changed_side == "subject" else candidate_id
    if change == "amount":
        changed = patch_expense(client, changed_id, headers=identity.app_headers, fields={"amount_cents": 2888})
    elif change == "ignore":
        snapshot = client.get(f"/api/expenses/{changed_id}", headers=identity.app_headers).json()
        changed = client.post(f"/api/expenses/{changed_id}/reject",
            headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"expected_row_version": snapshot["row_version"]})
    else:
        confirmed = confirm_expense_api(client, changed_id, headers=identity.app_headers)
        assert confirmed.status_code == 200, confirmed.text
        changed = client.post(f"/api/expenses/{changed_id}/offsets",
            headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"kind": "reversal", "accounting_date": datetime.now(UTC).date().isoformat(),
                "reason": "撤销这笔消费", "expected_row_version": confirmed.json()["row_version"]})
    assert changed.status_code in {200, 201}, changed.text
    with SessionLocal() as db:
        event = db.get(LedgerLearningEvent, event_id)
        assert event.after_payload == original_payload
        assert eligible_feedback(db, tenant_id="owner", events=[event], actor_account_id=event.actor_account_id) == []


def test_pending_api_returns_category_suggestion_and_reuses_decision(
    client: TestClient, *, identity
) -> None:
    for day in (1, 2, 3):
        _confirmed(
            client,
            identity=identity,
            merchant="全家便利店",
            category="餐饮",
            day=day,
        )
    pending_id = _pending_notification(
        client, identity=identity, merchant="全家便利店"
    )

    first = client.get("/api/expenses/pending", headers=identity.app_headers)
    second = client.get("/api/expenses/pending", headers=identity.app_headers)

    assert first.status_code == 200, first.json()
    assert second.status_code == 200, second.json()
    item = next(row for row in first.json() if row["id"] == pending_id)
    suggestion = item["category_suggestion"]
    assert suggestion["category"] == "餐饮"
    assert suggestion["sample_size"] == 3
    assert suggestion["decision_public_id"]
    assert item["duplicate_candidates"] == []

    with SessionLocal() as db:
        count = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.tenant_id == "owner")
            .filter(AlgorithmDecision.subject_id == pending_id)
            .filter(AlgorithmDecision.decision_type == "category_suggestion")
            .count()
        )
    assert count == 1


def test_pending_api_returns_duplicate_candidate(client: TestClient, *, identity) -> None:
    first = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("first.png", PNG_BYTES, "image/png")},
    )
    second = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("second.png", PNG_BYTES, "image/png")},
    )
    assert first.status_code == 200, first.json()
    assert second.status_code == 200, second.json()

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200, pending.json()
    item = next(row for row in pending.json() if row["id"] == second.json()["id"])
    candidates = item["duplicate_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["candidate_id"] == first.json()["id"]
    assert "image_hash_match" in candidates[0]["reasons"]
    assert "transaction_evidence_incomplete" in candidates[0]["reasons"]
    assert candidates[0]["decision_public_id"]


def test_pending_suggestion_accept_and_reject_write_learning_events(
    client: TestClient, *, identity
) -> None:
    for day in (1, 2, 3):
        _confirmed(
            client,
            identity=identity,
            merchant="咖啡小店",
            category="餐饮",
            day=day,
        )
    pending_id = _pending_notification(client, identity=identity, merchant="咖啡小店")
    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    decision_public_id = next(
        row for row in pending.json() if row["id"] == pending_id
    )["category_suggestion"]["decision_public_id"]

    accepted = client.post(
        f"/api/expenses/{pending_id}/suggestions/{decision_public_id}/accept",
        headers=identity.app_headers,
    )
    rejected = client.post(
        f"/api/expenses/{pending_id}/suggestions/{decision_public_id}/reject",
        headers=identity.app_headers,
    )
    corrected = client.post(f"/api/expenses/{pending_id}/suggestions/{decision_public_id}/accept",
        headers=identity.app_headers)
    replayed = client.post(f"/api/expenses/{pending_id}/suggestions/{decision_public_id}/accept",
        headers=identity.app_headers)

    assert accepted.status_code == 200, accepted.json()
    assert rejected.status_code == 200, rejected.json()
    assert corrected.status_code == replayed.status_code == 200
    with SessionLocal() as db:
        rows = (
            db.query(LedgerLearningEvent)
            .filter(LedgerLearningEvent.tenant_id == "owner")
            .filter(LedgerLearningEvent.subject_id == pending_id)
            .order_by(LedgerLearningEvent.id.asc())
            .all()
        )
        from app.services.learning_service._source_eligibility import eligible_feedback
        eligible = eligible_feedback(db, tenant_id="owner", events=rows, actor_account_id=rows[-1].actor_account_id)
        assert [row.id for row in eligible] == [rows[-1].id]
    assert [row.event_type for row in rows] == ["accept", "reject", "accept"]
    payloads = [json.loads(row.after_payload) for row in rows]
    assert [row["_feedback_revision"] for row in payloads] == [1, 2, 3]
    assert payloads[1]["_supersedes_event_public_id"] == rows[0].public_id
    assert payloads[2]["_supersedes_event_public_id"] == rows[1].public_id
    assert json.loads(rows[-1].before_payload or "{}") == {"category": "餐饮"}


def test_pending_suggestion_feedback_is_tenant_scoped(
    client: TestClient, *, identity
) -> None:
    for day in (1, 2, 3):
        _confirmed(
            client,
            identity=identity,
            merchant="租户隔离店",
            category="餐饮",
            day=day,
        )
    pending_id = _pending_notification(client, identity=identity, merchant="租户隔离店")
    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    decision_public_id = next(
        row for row in pending.json() if row["id"] == pending_id
    )["category_suggestion"]["decision_public_id"]

    blocked = client.post(
        f"/api/expenses/{pending_id}/suggestions/{decision_public_id}/accept",
        headers=identity.gray_app_headers,
    )

    assert blocked.status_code == 404


def test_pending_feedback_rejects_unknown_decision(
    client: TestClient, *, identity
) -> None:
    pending_id = _pending_notification(client, identity=identity, merchant="无建议店")
    response = client.post(
        f"/api/expenses/{pending_id}/suggestions/not-a-decision/reject",
        headers=identity.app_headers,
    )
    assert response.status_code == 404


def test_pending_suggestion_feedback_requires_auth(client: TestClient, *, identity) -> None:
    pending_id = _pending_notification(client, identity=identity, merchant="鉴权店")

    accept = client.post(
        f"/api/expenses/{pending_id}/suggestions/not-a-decision/accept"
    )
    reject = client.post(
        f"/api/expenses/{pending_id}/suggestions/not-a-decision/reject"
    )

    assert accept.status_code == 401
    assert reject.status_code == 401


def test_feedback_changes_the_next_real_review_without_changing_money(client, web_client, identity):
    """Read -> correct -> reopen -> next receipt, across the actual consumers."""
    from api_contract_helpers import confirm_expense_api, patch_expense

    from app.models import Expense

    for day in (1, 2, 3):
        _confirmed(client, identity=identity, merchant="学习咖啡店", category="餐饮", day=day)
    pending_id = _pending_notification(client, identity=identity, merchant="学习咖啡店")
    detail = client.get(f"/api/expenses/{pending_id}", headers=identity.app_headers).json()
    suggestion = detail["category_suggestion"]
    assert suggestion and suggestion["category"] == "餐饮"
    page = web_client.get(f"/web/expenses/{pending_id}/edit?ledger_id=owner")
    assert 'data-category-suggestion="餐饮"' in page.text
    assert "3 笔" in page.text

    # Replacing the merchant makes the old advice irrelevant, not a rejected category for the new shop.
    replaced_id = _pending_notification(client, identity=identity, merchant="学习咖啡店")
    assert client.get(f"/api/expenses/{replaced_id}", headers=identity.app_headers).json()["category_suggestion"]
    replaced = patch_expense(client, replaced_id, headers=identity.app_headers,
        fields={"merchant": "新商家", "category": "购物"})
    assert replaced.status_code == 200
    confirmed = confirm_expense_api(client, replaced_id, headers=identity.app_headers)
    assert confirmed.status_code == 200, confirmed.text
    with SessionLocal() as db:
        assert db.query(LedgerLearningEvent).filter(LedgerLearningEvent.subject_id == replaced_id).count() == 0
        assert db.get(Expense, replaced_id).merchant == "新商家"
        assert db.get(Expense, replaced_id).amount_cents == 1888

    intervening = patch_expense(client, pending_id, headers=identity.app_headers, fields={"note": "另一端刚保存"})
    assert intervening.status_code == 200
    stale = client.patch(f"/api/expenses/{pending_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"category": "购物", "expected_row_version": detail["row_version"]})
    assert stale.status_code == 409
    with SessionLocal() as db:
        assert db.query(LedgerLearningEvent).filter(LedgerLearningEvent.subject_id == pending_id).count() == 0

    changed = patch_expense(client, pending_id, headers=identity.app_headers, fields={"category": "购物"})
    assert changed.status_code == 200, changed.text
    # A stored feedback row alone is not the outcome: reopening must honour it.
    reopened = client.get(f"/api/expenses/{pending_id}", headers=identity.app_headers).json()
    assert reopened["category_suggestion"] is None
    assert reopened["category"] == "购物" and reopened["amount_cents"] == 1888

    second_id = _pending_notification(client, identity=identity, merchant="学习咖啡店")
    second = client.get(f"/api/expenses/{second_id}", headers=identity.app_headers).json()
    assert second_id != pending_id, second
    assert second["category_suggestion"] is not None, second
    decision_id = second["category_suggestion"]["decision_public_id"]
    rejected = client.post(f"/api/expenses/{second_id}/suggestions/{decision_id}/reject", headers=identity.app_headers)
    assert rejected.status_code == 200
    third_id = _pending_notification(client, identity=identity, merchant="学习咖啡店")
    third = client.get(f"/api/expenses/{third_id}", headers=identity.app_headers).json()
    assert third["category_suggestion"] is None  # Two corrections suppress the same merchant/category.
    with SessionLocal() as db:
        assert db.get(Expense, third_id).category == "其他"
        assert db.get(Expense, third_id).amount_cents == 1888
        events = db.query(LedgerLearningEvent).filter(LedgerLearningEvent.subject_id.in_([pending_id, second_id])).all()
        assert [e.event_type for e in sorted(events, key=lambda e: e.id)] == ["reject", "reject"]


def test_keep_both_excludes_only_that_pair_and_preserves_other_candidates(client, web_client, identity):
    from api_contract_helpers import patch_expense

    first_id = _pending_notification(client, identity=identity, merchant="重复核对店")
    second_id = _pending_notification(client, identity=identity, merchant="重复核对店")
    before = client.get(f"/api/expenses/{second_id}", headers=identity.app_headers).json()
    assert before["duplicate_candidates"]
    original_score = before["duplicate_candidates"][0]["score"]
    kept = client.post(f"/api/expenses/{second_id}/mark-not-duplicate",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": before["row_version"],
            "duplicate_decision_public_id": before["duplicate_candidates"][0]["decision_public_id"]})
    assert kept.status_code == 200, kept.text
    third_id = _pending_notification(client, identity=identity, merchant="重复核对店")
    after = client.get(f"/api/expenses/{third_id}", headers=identity.app_headers).json()
    assert {item["candidate_id"] for item in after["duplicate_candidates"]} == {first_id, second_id}
    assert all(item["score"] == original_score for item in after["duplicate_candidates"])
    assert len({item["decision_public_id"] for item in after["duplicate_candidates"]}) == 2
    repeated = client.get(f"/api/expenses/{third_id}", headers=identity.app_headers).json()
    assert repeated["duplicate_candidates"] == after["duplicate_candidates"]
    page = web_client.get(f"/web/duplicates?ledger_id=owner&focus={third_id}")
    assert f'data-duplicate-candidate-id="{second_id}"' in page.text
    assert "本次选择只针对上方参考账单" in page.text
    kept_third = client.post(f"/api/expenses/{third_id}/mark-not-duplicate",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": after["row_version"],
            "duplicate_decision_public_id": next(item["decision_public_id"] for item in after["duplicate_candidates"]
                if item["candidate_id"] == after["duplicate_of_id"])})
    assert kept_third.status_code == 200, kept_third.text
    assert kept_third.json()["duplicate_status"] == "suspected"
    assert kept_third.json()["duplicate_of_id"] == second_id
    remaining = client.get(f"/api/expenses/{third_id}", headers=identity.app_headers).json()
    assert [item["candidate_id"] for item in remaining["duplicate_candidates"]] == [second_id]
    for _ in range(2):
        _pending_notification(client, identity=identity, merchant="重复核对店")
    page = web_client.get("/web/duplicates?ledger_id=owner")
    assert "这个历史决定不代替当前两笔的核对" not in page.text
    for expense_id in (first_id, second_id):
        expense = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
        assert expense["amount_cents"] == 1888 and expense["status"] == "pending"

    # Correcting a field used by this duplicate verdict invalidates only that
    # evidence. Its original event remains available in the impact preview.
    changed = patch_expense(client, second_id, headers=identity.app_headers, fields={"amount_cents": 2888})
    assert changed.status_code == 200, changed.text
    next_id = _pending_notification(client, identity=identity, merchant="重复核对店")
    next_read = client.get(f"/api/expenses/{next_id}", headers=identity.app_headers).json()
    assert "recent_user_reject" not in next_read["duplicate_candidates"][0]["reasons"]
    from app.services.learning_service._source_eligibility import feedback_impact_preview
    with SessionLocal() as db:
        preview = feedback_impact_preview(db, tenant_id="owner")
        assert preview["superseded"] == 1
        assert db.query(LedgerLearningEvent).filter(LedgerLearningEvent.subject_id == second_id).count() == 1


@pytest.mark.parametrize("resolution", ["keep_both", "keep_subject", "keep_candidate"])
def test_pair_business_action_records_relation_once_and_undo_invalidates_it(client, identity, resolution):
    from app.models import Expense
    from app.services.expense_review_command_service import reject_duplicate_original_keep_current
    from app.services.learning_service._source_eligibility import eligible_feedback
    from tests._infra.identity import seeded_owner_account_id

    candidate_id = _pending_notification(client, identity=identity, merchant="原配对与保留动作")
    subject_id = _pending_notification(client, identity=identity, merchant="原配对与保留动作")
    detail = client.get(f"/api/expenses/{subject_id}", headers=identity.app_headers).json()
    candidate = client.get(f"/api/expenses/{candidate_id}", headers=identity.app_headers).json()
    decision_id = next(item["decision_public_id"] for item in detail["duplicate_candidates"] if item["candidate_id"] == candidate_id)
    operation_key = str(uuid4())
    actor = seeded_owner_account_id()
    for _ in range(2):
        if resolution == "keep_subject":
            with SessionLocal() as db:
                reject_duplicate_original_keep_current(db, current_expense_id=subject_id, original_expense_id=candidate_id,
                    tenant_id="owner", expected_row_version=detail["row_version"],
                    expected_original_row_version=candidate["row_version"], idempotency_key=operation_key,
                    actor_account_id=actor, duplicate_decision_public_id=decision_id)
        else:
            action = "reject" if resolution == "keep_candidate" else "mark-not-duplicate"
            response = client.post(f"/api/expenses/{subject_id}/{action}",
                headers={**identity.app_headers, "Idempotency-Key": operation_key},
                json={"expected_row_version": detail["row_version"], "duplicate_decision_public_id": decision_id})
            assert response.status_code == 200, response.text
    with SessionLocal() as db:
        event = db.query(LedgerLearningEvent).filter_by(subject_id=subject_id).one()
        event_id, original = event.id, event.after_payload
        label = json.loads(original)
        assert label["_relation"] == ("distinct" if resolution == "keep_both" else "same")
        assert label["_resolution"] == resolution and label["_operation_key"] == operation_key
        assert eligible_feedback(db, tenant_id="owner", events=[event], actor_account_id=actor) == [event]
        assert [db.get(Expense, key).amount_cents for key in (subject_id, candidate_id)] == [1888, 1888]
    if resolution != "keep_both":
        removed_id = candidate_id if resolution == "keep_subject" else subject_id
        removed = client.get(f"/api/expenses/{removed_id}", headers=identity.app_headers).json()
        restored = client.post(f"/api/expenses/{removed_id}/undo",
            headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"expected_row_version": removed["row_version"]})
        assert restored.status_code == 200, restored.text
        with SessionLocal() as db:
            event = db.get(LedgerLearningEvent, event_id)
            assert event.after_payload == original
            assert eligible_feedback(db, tenant_id="owner", events=[event], actor_account_id=actor) == []


def test_old_pair_version_cannot_label_or_discard_a_changed_reference(client, identity):
    from api_contract_helpers import patch_expense
    candidate_id = _pending_notification(client, identity=identity, merchant="配对版本核对")
    subject_id = _pending_notification(client, identity=identity, merchant="配对版本核对")
    detail = client.get(f"/api/expenses/{subject_id}", headers=identity.app_headers).json()
    decision_id = next(item["decision_public_id"] for item in detail["duplicate_candidates"] if item["candidate_id"] == candidate_id)
    changed = patch_expense(client, candidate_id, headers=identity.app_headers, fields={"note": "后来补充"})
    assert changed.status_code == 200, changed.text
    response = client.post(f"/api/expenses/{subject_id}/reject",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": detail["row_version"], "duplicate_decision_public_id": decision_id})
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.query(LedgerLearningEvent).filter_by(subject_id=subject_id).count() == 0
    assert client.get(f"/api/expenses/{subject_id}", headers=identity.app_headers).json()["status"] == "pending"
