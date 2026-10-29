"""Replay existing production API, feedback qualification and withdrawal owners.

Called only by the owned PostgreSQL test lane. Predictions are recorded before
the publisher oracle is consulted. Holdout labels never enter a write command.
"""
import hashlib
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense, LedgerLearningEvent
from app.schemas import ExpenseUpdateRequest
from app.services.currency_binding_service import resolve_write_capability
from app.services.exchange_rate_service import apply_currency_payload
from app.services.file_service import save_original_replenishment_bytes
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.learning_service._source_eligibility import feedback_assessments
from app.services.learning_service._withdrawal import withdraw_feedback
from app.services.recognition_amount_case import amount_case_contexts
from scripts.ocr_benchmark_metrics import score
from scripts.ocr_feedback_replay_data import ReplayMaterial


def _seed(material: ReplayMaterial) -> tuple[int, list[str]]:
    inputs, snapshot = material.fixture.inputs, material.snapshot
    body = inputs.image.read_bytes()
    if hashlib.sha256(body).hexdigest() != inputs.image_sha256:
        raise ValueError("original changed before replay")
    saved = save_original_replenishment_bytes(body, tenant_id="owner", expected_sha256=inputs.image_sha256,
        filename=inputs.image.name,
        content_type="image/jpeg" if inputs.image.suffix.lower() in {".jpg", ".jpeg"} else "image/" + inputs.image.suffix[1:])
    with SessionLocal.begin() as db:
        capability = resolve_write_capability(db)
        expense = Expense(tenant_id="owner", source="camera", status="pending", category="其他",
            merchant=snapshot["parsed_merchant"] or "", amount_cents=None, original_amount_minor=None,
            original_currency_code=inputs.currency_code, home_currency_code=capability.home_currency_code,
            image_path=saved.relative_path, image_hash=saved.image_hash, created_at=datetime.now(UTC))
        db.add(expense)
        db.flush()
        if snapshot["parsed_amount_cents"] is not None:
            apply_currency_payload(db, tenant_id="owner", home_currency_code=expense.home_currency_code, expense=expense,
                payload=ExpenseUpdateRequest(expected_row_version=expense.row_version, original_currency_code=inputs.currency_code,
                    original_amount_minor=snapshot["parsed_amount_cents"], manual_exchange_rate=Decimal("1")), amount_was_explicit=True)
        fact = record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=expense.id, ocr_provider="rapidocr",
            raw_text=snapshot["raw_text"], evidence_json=json.dumps(snapshot["evidence"]),
            parsed_amount_cents=snapshot["parsed_amount_cents"], parsed_merchant=snapshot["parsed_merchant"],
            parsed_category=snapshot["parsed_category"], parse_confidence=snapshot["parse_confidence"],
            parsed_expense_time=datetime.fromisoformat(snapshot["parsed_expense_time"]) if snapshot["parsed_expense_time"] else None))
        return expense.id, sorted({item["scope"] for item in amount_case_contexts(fact).values()})


def _response(response) -> dict:
    if response.status_code != 200:
        raise RuntimeError(f"production API returned HTTP {response.status_code}")
    return response.json()


def _prediction(current: dict, material: ReplayMaterial) -> dict:
    candidates = [row for row in current["recognition_fields"] if row["field"] == "amount_cents" and row["can_apply"]]
    first = candidates[0] if candidates else None
    amount = {"minor": first["value"], "currency": first["currency_code"]} if first else None
    matching = sum(score({"amount": {"minor": row["value"], "currency": row["currency_code"]}},
        material.fixture.labels)["amount"] is True for row in candidates)
    return {"first_candidate": amount, "candidate_correct": score({"amount": amount}, material.fixture.labels)["amount"],
        "correct_candidate_count": matching,
        "memory_suggested": first is not None and first["selection_intent"] == "bookkeeping",
        "candidates": candidates, "financial_minor_before": current["original_amount_minor"],
        "row_version_before": current["row_version"]}


def _oracle_payload(current: dict, material: ReplayMaterial, mode: str) -> dict | None:
    label = material.fixture.labels["amount"]
    if material.fixture.split == "holdout" or label.state != "present":
        return None
    payload = {"expected_row_version": current["row_version"], "original_currency_code": label.value["currency"],
        "original_amount_minor": label.value["minor"], "manual_exchange_rate": "1"}
    choices = [row for row in current["recognition_fields"] if row["field"] == "amount_cents" and row["can_apply"]
        and row["value"] == label.value["minor"] and row["currency_code"] == label.value["currency"]]
    if mode != "baseline" and len(choices) == 1:
        chosen = choices[0]
        payload["recognition_field_choices"] = [{"field": chosen["field"], "evidence_public_id": chosen["evidence_public_id"],
            "candidate_id": chosen["id"], "parser_version": chosen["parser_version"], "intent": chosen["selection_intent"]}]
    return payload


def _feedback_state(expense_id: int, mode: str) -> dict:
    with SessionLocal.begin() as db:
        events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == expense_id,
            LedgerLearningEvent.signal_type == "recognition_field_choice")))
        assessments = feedback_assessments(db, tenant_id="owner", events=events)
        valid = [event for event in events if assessments[event.id][0] == "valid"]
        if mode == "withdrawn":
            for event in valid:
                withdraw_feedback(db, tenant_id="owner", public_id=event.public_id)
        return {"events": len(events), "qualified": len(valid), "withdrawn": len(valid) if mode == "withdrawn" else 0,
            "assessment_before_withdrawal": [assessments[event.id][0] for event in events]}


def _replay_one(client, headers: dict, material: ReplayMaterial, mode: str) -> dict:
    expense_id, scopes = _seed(material)
    original = client.get(f"/api/expenses/{expense_id}/image", headers=headers)
    digest = material.fixture.inputs.image_sha256
    if (original.status_code != 200 or original.headers.get("etag") != f'"{digest}"'
            or hashlib.sha256(original.content).hexdigest() != digest):
        raise RuntimeError("frozen original could not be read with its recorded hash")
    current = _response(client.get(f"/api/expenses/{expense_id}", headers=headers))
    result = _prediction(current, material)
    result["original_verified_sha256"] = digest
    result["amount_context_scopes"] = scopes
    # No oracle values were used to seed the original or request the prediction.
    payload = _oracle_payload(current, material, mode)
    if payload is not None:
        command_headers = {**headers, "Idempotency-Key": str(uuid4())}
        saved = _response(client.patch(f"/api/expenses/{expense_id}", headers=command_headers, json=payload))
        replay = _response(client.patch(f"/api/expenses/{expense_id}", headers=command_headers, json=payload))
        if saved != replay or saved["original_amount_minor"] != payload["original_amount_minor"]:
            raise RuntimeError("financial correction or stable command replay changed")
        result["receipt_sha256"] = hashlib.sha256(json.dumps(saved, sort_keys=True).encode()).hexdigest()
        result["saved_financial_minor"] = saved["original_amount_minor"]
    else:
        latest = _response(client.get(f"/api/expenses/{expense_id}", headers=headers))
        if (latest["row_version"], latest["original_amount_minor"]) != (current["row_version"], current["original_amount_minor"]):
            raise RuntimeError("reading suggestions changed financial state")
    result["feedback"] = _feedback_state(expense_id, mode)
    return result


def replay(client, headers: dict, materials: list[ReplayMaterial], mode: str) -> dict:
    if mode not in {"baseline", "feedback", "withdrawn"}:
        raise ValueError("unknown feedback replay mode")
    rows, development_scopes = [], set()
    for sequence, material in enumerate(materials):
        row = {"sequence": sequence, "sample": material.fixture.name, "group_id": material.fixture.group_id,
            "split": material.fixture.split, "image_sha256": material.fixture.inputs.image_sha256,
            "original_outcome": material.original_outcome, "label_state": material.fixture.labels["amount"].state,
            "started_at": datetime.now(UTC).isoformat()}
        minor = material.snapshot["parsed_amount_cents"] if material.snapshot else None
        row["raw_amount"] = {"minor": minor, "currency": material.fixture.inputs.currency_code} if minor is not None else None
        row["raw_correct"] = score({"amount": row["raw_amount"]}, material.fixture.labels,
            failed=material.original_outcome != "success")["amount"]
        started = time.perf_counter()
        try:
            if material.original_outcome != "success":
                row["outcome"] = "original_failure"
            else:
                row.update(_replay_one(client, headers, material, mode), outcome="success")
                scopes = set(row["amount_context_scopes"])
                row["material_context"] = ("seen_development_context" if scopes & development_scopes
                    else "new_amount_context" if scopes else "no_comparable_amount_context")
                if material.fixture.split == "development":
                    development_scopes.update(scopes)
        except (AppError, OSError, RuntimeError, SQLAlchemyError, ValueError) as error:
            # Raw SQL/HTTP errors may contain private material. The bounded
            # type and failed sample locate the attempt without copying it.
            row.update(outcome="replay_error", error_type=type(error).__name__)
        row["service_elapsed_ms"] = (time.perf_counter() - started) * 1000
        rows.append(row)
    return {"mode": mode, "rows": rows, "attempted": len(rows), "product_qualified": False,
        "limitations": ["Reuses hash-bound actual native recordings; does not rerun inference",
            "Declared replay arrival order, not a reconstruction of historical user arrivals",
            "Publisher oracle actions, not human feedback, operation counts or time",
            "Explicit controlled FX rate 1 for replay accounting only; not a market-rate claim",
            "Amount suggestion ranking is separate from the retained original prediction and financial fact"]}
