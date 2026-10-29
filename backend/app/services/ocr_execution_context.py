"""Attempt identity on the existing durable task, separate from input and result."""

import json
from dataclasses import asdict

from app import config
from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask
from app.services.background_task_handler_api import TaskCancelledError
from app.services.ocr_service._models import OcrRun
from app.services.ocr_worker_client import configured_ocr_runtime_identity
from app.services.receipt_parse_common import FIELD_PARSE_VERSION
from app.services.time_service import now_utc


def begin_ocr_execution(task_id: int | None, *, mode: str) -> None:
    if task_id is None:
        return
    settings = config.get_settings()
    configured = {"provider": settings.ocr_provider, "fallback_provider": settings.ocr_fallback_provider,
        "auto_run": settings.ocr_auto_run, "local_llm_model": settings.local_llm_model,
        "field_parse_version": FIELD_PARSE_VERSION}
    if mode == "region" or any(name in {"rapidocr", "rapid_ocr"} for name in (
        settings.ocr_provider.strip().lower(), settings.ocr_fallback_provider.strip().lower()
    )):
        configured["rapidocr"] = configured_ocr_runtime_identity()
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id, with_for_update=True)
        if task is None:
            raise AppError("task_not_found", status_code=404)
        if task.cancellation_requested_at is not None:
            raise TaskCancelledError
        task.execution_context_json = json.dumps({"attempt": task.recovery_attempts + 1, "mode": mode,
            "started_at": now_utc().isoformat(), "configured": configured}, sort_keys=True, separators=(",", ":"))
        db.commit()


def finish_ocr_execution(task_id: int | None, run: OcrRun) -> None:
    if task_id is None:
        return
    observed = []
    for extraction in run.extractions:
        evidence = extraction.result.evidence or {}
        # A regional result also carries the preceding full-image identity.
        identity = evidence.get("regional_retry", evidence).get("identity")
        observed.append({"provider": extraction.provider_name, "model": extraction.ocr_model,
            "identity": identity})
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id, with_for_update=True)
        if task is None:
            raise AppError("task_not_found", status_code=404)
        context = json.loads(task.execution_context_json)
        context.update(observed=observed, providers=[asdict(attempt) for attempt in run.attempts],
            inference_returned_at=now_utc().isoformat())
        task.execution_context_json = json.dumps(context, sort_keys=True, separators=(",", ":"))
        db.commit()
