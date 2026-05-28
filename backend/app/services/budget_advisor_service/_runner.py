"""Shared API and /web execution path for budget advisor calls."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.services.budget_advisor_service._audit import (
    compute_input_hash,
    enforce_live_call_budget,
    is_live_provider,
    record_audit_row,
)
from app.services.budget_advisor_service._inputs_builder import build_budget_inputs
from app.services.budget_advisor_service._models import BudgetAdvice
from app.services.budget_advisor_service._outbound_guard import to_outbound_dict
from app.services.budget_advisor_service._provider_names import canonical_provider_name
from app.services.budget_advisor_service._providers import get_budget_advisor


@dataclass(frozen=True)
class AdvisorRunResult:
    provider_name: str
    advice: BudgetAdvice | None


_LIVE_CALL_LOCKS_LOCK = threading.Lock()
_LIVE_CALL_LOCKS: dict[str, threading.Lock] = {}


@contextmanager
def _live_call_lock(tenant_id: str, *, enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return
    with _LIVE_CALL_LOCKS_LOCK:
        lock = _LIVE_CALL_LOCKS.setdefault(tenant_id, threading.Lock())
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def run_budget_advisor(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int | None,
    actor_role: str,
    month: str,
    timezone_name: str,
) -> AdvisorRunResult:
    """Run the configured provider with identical gates for API and /web."""

    cfg = get_settings()
    provider_name = canonical_provider_name(cfg.budget_advisor_provider)
    provider_is_live = is_live_provider(provider_name)
    with _live_call_lock(tenant_id, enabled=provider_is_live):
        if provider_is_live:
            if not cfg.budget_advisor_owner_confirmed:
                raise AppError("ai_advisor_not_confirmed", status_code=403)
            if actor_role != "owner":
                raise AppError("ai_advisor_owner_required", status_code=403)
            enforce_live_call_budget(db, tenant_id=tenant_id)

        inputs = build_budget_inputs(
            db,
            tenant_id=tenant_id,
            month=month,
            timezone_name=timezone_name,
        )
        advisor = get_budget_advisor()
        started = perf_counter()
        advice: BudgetAdvice | None = None
        error_code: str | None = None
        try:
            advice = advisor.advise(inputs)
            if provider_is_live and advice is None:
                error_code = "ai_advisor_no_advice"
        except AppError as exc:
            error_code = exc.error
            raise
        finally:
            if provider_is_live:
                duration_ms = int((perf_counter() - started) * 1000)
                try:
                    outbound = to_outbound_dict(inputs)
                    input_hash = compute_input_hash(outbound)
                except Exception:  # noqa: BLE001 - audit must not abort response
                    input_hash = "unknown"
                record_audit_row(
                    db,
                    tenant_id=tenant_id,
                    actor_account_id=actor_account_id,
                    provider=provider_name,
                    model=cfg.budget_advisor_model or None,
                    base_url=cfg.budget_advisor_base_url or None,
                    month=month,
                    input_hash=input_hash,
                    success=advice is not None and error_code is None,
                    error_code=error_code,
                    suggestion_count=(
                        len(advice.suggestions) if advice is not None else 0
                    ),
                    duration_ms=duration_ms,
            )
    return AdvisorRunResult(provider_name=provider_name, advice=advice)
