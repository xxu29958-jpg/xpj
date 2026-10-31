"""Development-only, PostgreSQL-enforced read-only replay of existing labels."""

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import LedgerLearningEvent, OcrFact
from app.services.learning_service._source_eligibility import _event_payload, feedback_assessments
from app.services.receipt_parse_common import FIELD_PARSE_VERSION
from app.services.receipt_parse_service import parse_receipt_text
from scripts.ocr_correction_binding import replay_label

SIGNALS = ("recognition_field_choice", "recognition_time_choice")
OUTCOMES = ("same", "fixed", "broken", "unbindable")


def _replay(db, *, tenant_id, actor_account_id, parser):
    events = list(db.scalars(select(LedgerLearningEvent).where(
        LedgerLearningEvent.tenant_id == tenant_id, LedgerLearningEvent.actor_account_id == actor_account_id,
        LedgerLearningEvent.signal_type.in_(SIGNALS), LedgerLearningEvent.event_type != "withdraw")
        .order_by(LedgerLearningEvent.id)))
    assessments = feedback_assessments(db, tenant_id=tenant_id, events=events)
    rows, exclusions = [], []
    for event in events:
        status, reason, _ = assessments[event.id]
        payload = _event_payload(event)
        if status != "valid":
            exclusions.append({"label": event.public_id, "status": status, "reason": reason})
            continue
        row = {"label": event.public_id, "field": payload.get("field"),
               "evidence": payload.get("evidence_public_id")}
        fact = db.scalar(select(OcrFact).where(OcrFact.tenant_id == tenant_id,
            OcrFact.expense_id == event.subject_id, OcrFact.public_id == payload.get("evidence_public_id")))
        if payload.get("source", "image") != "image" or fact is None:
            result = {"outcome": "unbindable", "reason": "no_image_fact"}
        else:
            try:
                result = replay_label(fact, payload, parser)
            except (ValueError, TypeError, KeyError, IndexError):
                result = {"outcome": "unbindable", "reason": "invalid_label_or_evidence"}
        rows.append({**row, **result})
    counts = Counter(row["outcome"] for row in rows)
    return {"schema": "ocr-correction-replay/v1", "parser_version": FIELD_PARSE_VERSION,
            "scope": {"tenant_id": tenant_id, "actor_account_id": actor_account_id},
            "label_events": len(events), "qualified": len(rows), "excluded": len(exclusions),
            "outcomes": {name: counts[name] for name in OUTCOMES},
            "selected_regressions": sum(bool(row.get("baseline_selected")) and not row.get("candidate_selected") for row in rows),
            "selected_fixes": sum(bool(row.get("candidate_selected")) and not row.get("baseline_selected") for row in rows),
            "exclusion_counts": dict(Counter(row["status"] for row in exclusions)),
            "labels": rows, "exclusions": exclusions}


def replay(engine, *, tenant_id, actor_account_id, parser=parse_receipt_text):
    if engine.dialect.name != "postgresql":
        raise ValueError("correction replay requires PostgreSQL read-only transaction enforcement")
    with engine.connect() as connection, connection.begin() as transaction:
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        with Session(bind=connection, autoflush=False) as db:
            report = _replay(db, tenant_id=tenant_id, actor_account_id=actor_account_id, parser=parser)
        transaction.rollback()
    return report


def main():
    from scripts.ocr_benchmark_data import sha256
    from scripts.ocr_feedback_replay import source_identity

    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--tenant-id", required=True)
    command.add_argument("--actor-account-id", type=int, required=True)
    command.add_argument("--output", type=Path, required=True)
    args = command.parse_args()
    identity = source_identity()
    if identity["working_status"]:
        raise ValueError("correction replay requires a clean source checkout for reproducible results")
    identity["correction_sources"] = {path.name: sha256(path) for path in Path(__file__).parent.glob("ocr_correction_*.py")}
    # Secrets stay in the caller's environment, never command arguments/output.
    engine = create_engine(os.environ["XPJ_CORRECTION_REPLAY_DATABASE_URL"])
    try:
        report = replay(engine, tenant_id=args.tenant_id, actor_account_id=args.actor_account_id)
        report["source"] = identity
    finally:
        engine.dispose()
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
