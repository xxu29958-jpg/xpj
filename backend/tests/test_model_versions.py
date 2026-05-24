"""v1.2 P3 — algorithm version inventory + rollback contract."""

from __future__ import annotations

from app.database import SessionLocal
from app.services.learning_service import (
    DecisionDraft,
    list_algorithm_versions,
    record_decision,
    supersede_decision,
    withdraw_algorithm_version,
)


def _emit(
    *,
    tenant_id: str = "owner",
    decision_type: str = "category_suggestion",
    algorithm_version: str = "category-rules-v1",
    subject_id: int = 1,
    category: str = "餐饮",
) -> int:
    with SessionLocal() as db:
        row = record_decision(
            db,
            DecisionDraft(
                tenant_id=tenant_id,
                decision_type=decision_type,
                algorithm_version=algorithm_version,
                subject_kind="expense",
                subject_id=subject_id,
                payload={"category": category},
            ),
        )
        db.commit()
        return row.id


def test_inventory_counts_status_buckets(*, identity) -> None:
    a = _emit(algorithm_version="v1", subject_id=1)
    _emit(algorithm_version="v1", subject_id=2)
    c = _emit(algorithm_version="v2", subject_id=1)
    # Mark `a` superseded by `c` so the v1 bucket has one active + one
    # superseded, and v2 has one active.
    with SessionLocal() as db:
        supersede_decision(
            db,
            tenant_id="owner",
            old_decision_id=a,
            new_decision_id=c,
        )
        db.commit()

        rows = list_algorithm_versions(db, tenant_id="owner")
        by_version = {(r.decision_type, r.algorithm_version): r for r in rows}
        v1 = by_version[("category_suggestion", "v1")]
        v2 = by_version[("category_suggestion", "v2")]
        assert v1.active_count == 1
        assert v1.superseded_count == 1
        assert v2.active_count == 1


def test_withdraw_flips_active_to_withdrawn(*, identity) -> None:
    _emit(algorithm_version="bad-model", subject_id=10)
    _emit(algorithm_version="bad-model", subject_id=11)
    _emit(algorithm_version="good-model", subject_id=12)
    with SessionLocal() as db:
        rowcount = withdraw_algorithm_version(
            db,
            tenant_id="owner",
            decision_type="category_suggestion",
            algorithm_version="bad-model",
        )
        db.commit()
        assert rowcount == 2

        rows = list_algorithm_versions(db, tenant_id="owner")
        bad = next(
            r for r in rows
            if r.algorithm_version == "bad-model"
        )
        good = next(
            r for r in rows
            if r.algorithm_version == "good-model"
        )
        assert bad.active_count == 0
        assert bad.withdrawn_count == 2
        assert good.active_count == 1
        assert good.withdrawn_count == 0


def test_withdraw_is_tenant_scoped(*, identity) -> None:
    _emit(tenant_id="owner", algorithm_version="bad", subject_id=1)
    _emit(tenant_id="tester_1", algorithm_version="bad", subject_id=1)
    with SessionLocal() as db:
        # Withdrawing the "owner" bucket must leave tester_1 alone.
        rowcount = withdraw_algorithm_version(
            db,
            tenant_id="owner",
            decision_type="category_suggestion",
            algorithm_version="bad",
        )
        db.commit()
        assert rowcount == 1
        tester_rows = list_algorithm_versions(db, tenant_id="tester_1")
        bad = next(r for r in tester_rows if r.algorithm_version == "bad")
        assert bad.active_count == 1
        assert bad.withdrawn_count == 0


def test_withdraw_idempotent_on_already_withdrawn(*, identity) -> None:
    _emit(algorithm_version="bad", subject_id=1)
    with SessionLocal() as db:
        first = withdraw_algorithm_version(
            db,
            tenant_id="owner",
            decision_type="category_suggestion",
            algorithm_version="bad",
        )
        db.commit()
        assert first == 1
        # Running it again on already-withdrawn rows matches zero.
        second = withdraw_algorithm_version(
            db,
            tenant_id="owner",
            decision_type="category_suggestion",
            algorithm_version="bad",
        )
        db.commit()
        assert second == 0
