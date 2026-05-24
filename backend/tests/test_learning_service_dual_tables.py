"""v1.2 P0 — learning feedback service contract.

Verifies the dual-table append-only model:

* ``record_decision`` writes ``algorithm_decisions`` rows with
  serialised JSON payloads and an initial ``status='active'``.
* ``record_event`` writes ``ledger_learning_events`` rows; the
  related decision's status is *not* auto-flipped (separate concern).
* ``supersede_decision`` only flips ``active`` rows within the same
  tenant; cross-tenant attempts are silently refused.
* The read-side helpers honour tenant scoping and respect subject
  identity (including ``subject_id is None`` for tenant-wide rows).
"""

from __future__ import annotations

import json

import pytest

from app.database import SessionLocal
from app.models import AlgorithmDecision, LedgerLearningEvent
from app.services.learning_service import (
    DecisionDraft,
    EventDraft,
    active_decision_for_subject,
    recent_events_for_subject,
    record_decision,
    record_event,
    supersede_decision,
)


def test_record_decision_persists_serialised_payload(*, identity) -> None:
    with SessionLocal() as db:
        row = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v1",
                subject_kind="expense",
                subject_id=1234,
                payload={"category": "餐饮", "confidence": 0.85},
                score=0.85,
            ),
        )
        db.commit()
        assert row.id is not None
        assert row.status == "active"
        assert json.loads(row.output_payload) == {
            "category": "餐饮",
            "confidence": 0.85,
        }


def test_record_event_links_to_decision_without_mutating_it(
    *, identity,
) -> None:
    with SessionLocal() as db:
        decision = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v1",
                subject_kind="expense",
                subject_id=9001,
                payload={"category": "餐饮"},
            ),
        )
        event = record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="reject",
                subject_kind="expense",
                subject_id=9001,
                decision_id=decision.id,
                actor_account_id=None,
                after_payload={"category": "购物"},
            ),
        )
        db.commit()
        assert event.decision_id == decision.id
        # Decision row must keep its 'active' status — rejecting a
        # suggestion doesn't make it obsolete by itself.
        db.refresh(decision)
        assert decision.status == "active"


def test_record_event_refuses_cross_tenant_decision_link(
    *, identity,
) -> None:
    with SessionLocal() as db:
        decision = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v1",
                subject_kind="expense",
                subject_id=9001,
                payload={"category": "餐饮"},
            ),
        )
        with pytest.raises(ValueError, match="another tenant"):
            record_event(
                db,
                EventDraft(
                    tenant_id="tester_1",
                    event_type="reject",
                    subject_kind="expense",
                    subject_id=9001,
                    decision_id=decision.id,
                ),
            )
        db.rollback()


def test_record_event_refuses_mismatched_subject(
    *, identity,
) -> None:
    with SessionLocal() as db:
        decision = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v1",
                subject_kind="expense",
                subject_id=9001,
                payload={"category": "餐饮"},
            ),
        )
        with pytest.raises(ValueError, match="subject id"):
            record_event(
                db,
                EventDraft(
                    tenant_id="owner",
                    event_type="reject",
                    subject_kind="expense",
                    subject_id=9002,
                    decision_id=decision.id,
                ),
            )
        db.rollback()


def test_manual_override_event_persists_without_decision(*, identity) -> None:
    with SessionLocal() as db:
        event = record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="manual_override",
                subject_kind="expense",
                subject_id=42,
                before_payload={"category": "其他"},
                after_payload={"category": "餐饮"},
            ),
        )
        db.commit()
        assert event.id is not None
        assert event.decision_id is None
        assert json.loads(event.before_payload) == {"category": "其他"}


def test_supersede_marks_old_active_row(*, identity) -> None:
    with SessionLocal() as db:
        old = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v1",
                subject_kind="expense",
                subject_id=7,
                payload={"category": "餐饮"},
            ),
        )
        new = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v2",
                subject_kind="expense",
                subject_id=7,
                payload={"category": "购物"},
            ),
        )
        rowcount = supersede_decision(
            db,
            tenant_id="owner",
            old_decision_id=old.id,
            new_decision_id=new.id,
        )
        db.commit()
        assert rowcount == 1
        db.refresh(old)
        db.refresh(new)
        assert old.status == "superseded"
        assert old.superseded_by_id == new.id
        assert new.status == "active"


def test_supersede_silently_refuses_cross_tenant(*, identity) -> None:
    with SessionLocal() as db:
        owner_decision = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="duplicate_candidate",
                algorithm_version="dup-v1",
                subject_kind="expense",
                subject_id=99,
                payload={"pair": [99, 100]},
            ),
        )
        tester_decision = record_decision(
            db,
            DecisionDraft(
                tenant_id="tester_1",
                decision_type="duplicate_candidate",
                algorithm_version="dup-v1",
                subject_kind="expense",
                subject_id=200,
                payload={"pair": [200, 201]},
            ),
        )
        db.commit()
        # Pretend a tester_1 actor accidentally tries to supersede an
        # owner-tenant decision: cross-tenant supersede must be a no-op.
        rowcount = supersede_decision(
            db,
            tenant_id="tester_1",
            old_decision_id=owner_decision.id,
            new_decision_id=tester_decision.id,
        )
        db.commit()
        assert rowcount == 0
        db.refresh(owner_decision)
        assert owner_decision.status == "active"


def test_supersede_refuses_cross_tenant_new_decision(*, identity) -> None:
    with SessionLocal() as db:
        owner_decision = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="duplicate_candidate",
                algorithm_version="dup-v1",
                subject_kind="expense",
                subject_id=99,
                payload={"pair": [99, 100]},
            ),
        )
        tester_decision = record_decision(
            db,
            DecisionDraft(
                tenant_id="tester_1",
                decision_type="duplicate_candidate",
                algorithm_version="dup-v2",
                subject_kind="expense",
                subject_id=99,
                payload={"pair": [99, 100]},
            ),
        )
        db.commit()
        rowcount = supersede_decision(
            db,
            tenant_id="owner",
            old_decision_id=owner_decision.id,
            new_decision_id=tester_decision.id,
        )
        db.commit()
        assert rowcount == 0
        db.refresh(owner_decision)
        assert owner_decision.status == "active"
        assert owner_decision.superseded_by_id is None


def test_supersede_refuses_different_subject(*, identity) -> None:
    with SessionLocal() as db:
        old = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v1",
                subject_kind="expense",
                subject_id=7,
                payload={"category": "餐饮"},
            ),
        )
        new = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v2",
                subject_kind="expense",
                subject_id=8,
                payload={"category": "餐饮"},
            ),
        )
        rowcount = supersede_decision(
            db,
            tenant_id="owner",
            old_decision_id=old.id,
            new_decision_id=new.id,
        )
        db.commit()
        assert rowcount == 0
        db.refresh(old)
        assert old.status == "active"
        assert old.superseded_by_id is None


def test_active_decision_returns_latest_only(*, identity) -> None:
    with SessionLocal() as db:
        older = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v1",
                subject_kind="expense",
                subject_id=11,
                payload={"category": "其他"},
            ),
        )
        # Supersede the older one to keep the contract clean ("active"
        # collection is by definition the non-superseded surface).
        newer = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v2",
                subject_kind="expense",
                subject_id=11,
                payload={"category": "餐饮"},
            ),
        )
        supersede_decision(
            db,
            tenant_id="owner",
            old_decision_id=older.id,
            new_decision_id=newer.id,
        )
        db.commit()
        latest = active_decision_for_subject(
            db,
            tenant_id="owner",
            decision_type="category_suggestion",
            subject_kind="expense",
            subject_id=11,
        )
        assert latest is not None
        assert latest.id == newer.id


def test_recent_events_filtered_by_type(*, identity) -> None:
    with SessionLocal() as db:
        for event_type in ("accept", "reject", "reject", "manual_override"):
            record_event(
                db,
                EventDraft(
                    tenant_id="owner",
                    event_type=event_type,
                    subject_kind="merchant",
                    subject_id=8,
                ),
            )
        db.commit()
        rejects = recent_events_for_subject(
            db,
            tenant_id="owner",
            subject_kind="merchant",
            subject_id=8,
            event_types=["reject"],
        )
        assert len(rejects) == 2
        assert all(e.event_type == "reject" for e in rejects)


def test_tenant_isolation_in_reads(*, identity) -> None:
    with SessionLocal() as db:
        record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="duplicate_candidate",
                algorithm_version="dup-v1",
                subject_kind="expense",
                subject_id=500,
                payload={"score": 0.9},
            ),
        )
        record_decision(
            db,
            DecisionDraft(
                tenant_id="tester_1",
                decision_type="duplicate_candidate",
                algorithm_version="dup-v1",
                subject_kind="expense",
                subject_id=500,
                payload={"score": 0.4},
            ),
        )
        db.commit()
        # Same subject_id across tenants must not bleed.
        owner_view = active_decision_for_subject(
            db,
            tenant_id="owner",
            decision_type="duplicate_candidate",
            subject_kind="expense",
            subject_id=500,
        )
        tester_view = active_decision_for_subject(
            db,
            tenant_id="tester_1",
            decision_type="duplicate_candidate",
            subject_kind="expense",
            subject_id=500,
        )
        assert owner_view is not None and tester_view is not None
        assert owner_view.id != tester_view.id
        assert owner_view.tenant_id == "owner"
        assert tester_view.tenant_id == "tester_1"


def test_tables_are_isolated_from_ledger(client, *, identity) -> None:
    # 建议层不污染账本 contract: writing to the learning tables must
    # never change the visible expense list. Use the API surface here
    # (no service-layer monkeypatching) to confirm.
    pending_before = client.get(
        "/api/expenses/pending", headers=identity.app_headers
    ).json()
    with SessionLocal() as db:
        decision = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-rules-v1",
                subject_kind="expense",
                subject_id=1,
                payload={"category": "餐饮"},
            ),
        )
        record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="accept",
                subject_kind="expense",
                subject_id=1,
                decision_id=decision.id,
            ),
        )
        db.commit()
    pending_after = client.get(
        "/api/expenses/pending", headers=identity.app_headers
    ).json()
    assert pending_before == pending_after

    # And the two tables actually picked up the writes (sanity).
    with SessionLocal() as db:
        assert (
            db.query(AlgorithmDecision).filter_by(tenant_id="owner").count()
            >= 1
        )
        assert (
            db.query(LedgerLearningEvent).filter_by(tenant_id="owner").count()
            >= 1
        )
