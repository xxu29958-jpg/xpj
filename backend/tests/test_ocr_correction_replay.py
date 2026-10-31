"""Upgrade regressions rebind values to original regions without touching the ledger."""
import hashlib
import json
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import AlgorithmDecision, Expense, LedgerLearningEvent, OcrFact
from app.schemas._recognition_fields import RecognitionFieldChoice
from app.services.currency_binding_service import resolve_write_capability
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.learning_service._algorithm_registry import RECOGNITION_FIELD_CHOICE
from app.services.learning_service._policy import set_policy
from app.services.learning_service._withdrawal import withdraw_feedback
from app.services.receipt_parse_service import parse_receipt_text
from app.services.recognition_choice_service import _candidate_components
from app.services.recognition_field_service import recognition_fields, record_field_choices
from app.services.recognition_time_service import recognition_time
from scripts.ocr_correction_binding import frozen_context, replay_label
from scripts.ocr_correction_replay import replay
from tests._infra.identity import seeded_owner_account_id
from tests.test_recognition_source import source_fact


def _label(fact, field="amount_cents"):
    candidate = (recognition_time(fact).candidates[0] if field == "expense_time" else
        next(item for item in recognition_fields(fact) if item.field == field and item.can_apply))
    return {"field": field, "selected": candidate.model_dump(), **(
        {"final_components": _candidate_components(candidate)} if field == "expense_time" else
        {"final_value": candidate.value})}


@pytest.mark.parametrize("field", ["amount_cents", "merchant", "expense_time"])
def test_parser_upgrade_can_change_ids_without_losing_label(field):
    fact = source_fact()
    def upgrade(*args, **kwargs):
        parsed = parse_receipt_text(*args, **kwargs)
        return replace(parsed, candidates=tuple(replace(item, id="upgraded-" + item.id) for item in parsed.candidates))
    result = replay_label(fact, _label(fact, field), upgrade)
    assert result["outcome"] == "same" and result["candidate_matches"] >= 1


def test_equal_amount_elsewhere_does_not_hide_a_broken_binding():
    fact = source_fact()
    label = _label(fact)
    def moved(*args, **kwargs):
        parsed = parse_receipt_text(*args, **kwargs)
        return replace(parsed, candidates=tuple(item for item in parsed.candidates if item.role != "payment"))
    result = replay_label(fact, label, moved)
    assert result["outcome"] == "broken" and result["candidate_matches"] == 0


def test_new_parser_can_fix_a_historical_numeric_reading():
    fact = source_fact()
    label = _label(fact)
    evidence = json.loads(fact.evidence_json)
    for item in evidence["field_parse"]["candidates"]:
        if item["field"] == "amount_cents" and item.get("role") == "payment":
            item["value"] = 490
    label["selected"]["value"] = 490
    fact.evidence_json = json.dumps(evidence)
    result = replay_label(fact, label, parse_receipt_text)
    assert result["outcome"] == "fixed" and result["candidate_matches"] >= 1


def test_missing_context_and_location_are_not_filled_from_current_settings():
    fact = source_fact()
    label = _label(fact)
    label["selected"]["source_location"] = None
    assert replay_label(fact, label, parse_receipt_text)["reason"] == "missing_label_location"
    assert frozen_context({"candidates": []}) is None
    parsed = json.loads(fact.evidence_json)["field_parse"]
    expected = parsed.pop("input_context")
    assert frozen_context(parsed) == expected
    assert frozen_context({"input_context": {"currency_code": "JPY", "minor_unit_exponent": 2}}) is None


def _seed_choice(*, with_location=True, field="amount_cents"):
    fact = source_fact()
    if not with_location:
        evidence = json.loads(fact.evidence_json)
        evidence.pop("blocks")
        fact.evidence_json = json.dumps(evidence)
    with SessionLocal() as db:
        resolve_write_capability(db)
        row = Expense(tenant_id="owner", source="camera", status="pending", category="其他", merchant="盒马",
            amount_cents=4990, original_amount_minor=4990, original_currency_code="CNY", home_currency_code="CNY",
            image_hash="a" * 64)
        db.add(row)
        db.flush()
        stored = record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=row.id, ocr_provider="mock",
            raw_text=fact.raw_text, evidence_json=fact.evidence_json))
        candidate = next(item for item in recognition_fields(stored) if item.field == field and item.can_apply)
        record_field_choices(db, expense=row, actor_account_id=seeded_owner_account_id(), choices=[
            RecognitionFieldChoice(field=field, candidate_id=candidate.id,
                evidence_public_id=stored.public_id, parser_version=candidate.parser_version)])
        event = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == row.id))
        db.commit()
        return event.public_id


def _fingerprint():
    with SessionLocal() as db:
        rows = {model.__tablename__: [dict(row) for row in db.execute(select(model.__table__).order_by(model.id)).mappings()]
                for model in (Expense, OcrFact, LedgerLearningEvent, AlgorithmDecision)}
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


@pytest.mark.real_db
def test_readonly_replay_keeps_exclusions_full_denominators_and_financial_versions(client, identity):
    _seed_choice()
    _seed_choice(with_location=False)
    withdrawn = _seed_choice()
    with SessionLocal() as db:
        withdraw_feedback(db, tenant_id="owner", public_id=withdrawn)
        db.commit()
    before = _fingerprint()
    result = replay(engine, tenant_id="owner", actor_account_id=seeded_owner_account_id())
    assert result["label_events"] == 3 and result["excluded"] == 1
    assert result["qualified"] == sum(result["outcomes"].values()) == 2
    assert result["outcomes"] == {"same": 1, "fixed": 0, "broken": 0, "unbindable": 1}
    assert any(row["label"] == withdrawn for row in result["exclusions"])
    assert _fingerprint() == before
    assert replay(engine, tenant_id="owner", actor_account_id=-1)["label_events"] == 0
    assert replay(engine, tenant_id="different-ledger", actor_account_id=seeded_owner_account_id())["label_events"] == 0
    with SessionLocal() as db:
        set_policy(db, tenant_id="owner", decision_type=RECOGNITION_FIELD_CHOICE.decision_type,
            version=RECOGNITION_FIELD_CHOICE.current_version, axis="training", enabled=False)
        db.commit()
    result = replay(engine, tenant_id="owner", actor_account_id=seeded_owner_account_id())
    assert result["qualified"] == 0 and result["excluded"] == 3
    assert result["exclusion_counts"]["quarantined"] == 2


@pytest.mark.real_db
def test_database_itself_refuses_writes_inside_the_replay_snapshot(client, identity, monkeypatch):
    from sqlalchemy.exc import DBAPIError

    import scripts.ocr_correction_replay as module

    _seed_choice()
    before = _fingerprint()
    def forbidden(db: Session, **kwargs):
        assert db.connection().exec_driver_sql("SHOW transaction_read_only").scalar() == "on"
        db.connection().exec_driver_sql("UPDATE expenses SET row_version = row_version + 1")
    monkeypatch.setattr(module, "_replay", forbidden)
    with pytest.raises(DBAPIError):
        replay(engine, tenant_id="owner", actor_account_id=seeded_owner_account_id())
    assert _fingerprint() == before
