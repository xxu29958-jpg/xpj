"""Shared API and /web execution path for budget advisor calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError, DataIntegrityError
from app.services.budget_advisor_service._audit import (
    complete_live_call_audit_row,
    compute_input_hash,
    is_live_provider,
    reserve_live_call_budget,
)
from app.services.budget_advisor_service._inputs_builder import build_budget_inputs
from app.services.budget_advisor_service._models import BudgetAdvice, BudgetInputs
from app.services.budget_advisor_service._outbound_guard import to_outbound_dict
from app.services.budget_advisor_service._provider_names import canonical_provider_name
from app.services.budget_advisor_service._providers import get_budget_advisor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdvisorRunResult:
    provider_name: str
    advice: BudgetAdvice | None
    reason_code: str | None = None


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
    if provider_is_live:
        _assert_live_advisor_allowed(actor_role=actor_role)

    inputs = build_budget_inputs(
        db,
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
    )
    advisor = get_budget_advisor()
    audit_log_id: int | None = None
    if provider_is_live:
        # Fail-closed outbound-schema guard runs once, before reserving the
        # live-call budget. A payload outside the contract yields a no-advice
        # result with a reason code instead of a raw 500 — the same outcome the
        # provider itself produces when it rejects the payload on the wire.
        try:
            input_hash = compute_input_hash(to_outbound_dict(inputs))
        except DataIntegrityError:
            logger.exception("budget advisor outbound payload rejected before live call")
            return AdvisorRunResult(
                provider_name=provider_name,
                advice=None,
                reason_code="ai_advisor_payload_invalid",
            )
        audit_log_id = _reserve_live_call(
            db,
            tenant_id=tenant_id,
            actor_account_id=actor_account_id,
            provider=provider_name,
            month=month,
            input_hash=input_hash,
        )

    return _invoke_and_record(
        db,
        advisor,
        inputs,
        provider_name=provider_name,
        provider_is_live=provider_is_live,
        audit_log_id=audit_log_id,
    )


def _invoke_and_record(
    db: Session,
    advisor: object,
    inputs: BudgetInputs,
    *,
    provider_name: str,
    provider_is_live: bool,
    audit_log_id: int | None,
) -> AdvisorRunResult:
    """Call the provider, map no-advice to a reason code, and always close the
    live-call audit row. Split out of [run_budget_advisor] so each stays focused
    and under the length budget."""
    started = perf_counter()
    advice: BudgetAdvice | None = None
    error_code: str | None = None
    reason_code: str | None = None
    try:
        advice = advisor.advise(inputs)
        if advice is None:
            reason_code = _advisor_reason_code(
                advisor,
                default=(
                    "ai_advisor_no_advice"
                    if provider_is_live
                    else f"ai_advisor_provider_{provider_name}"
                ),
            )
            if provider_is_live:
                error_code = reason_code
    except AppError as exc:
        error_code = exc.error
        reason_code = exc.error
        raise
    finally:
        if provider_is_live and audit_log_id is not None:
            _complete_live_call(
                db,
                audit_log_id=audit_log_id,
                started=started,
                advice=advice,
                error_code=error_code,
            )
    return AdvisorRunResult(
        provider_name=provider_name,
        advice=advice,
        reason_code=reason_code,
    )


def _assert_live_advisor_allowed(*, actor_role: str) -> None:
    cfg = get_settings()
    if not cfg.budget_advisor_owner_confirmed:
        raise AppError("ai_advisor_not_confirmed", status_code=403)
    if actor_role != "owner":
        raise AppError("ai_advisor_owner_required", status_code=403)


def _reserve_live_call(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int | None,
    provider: str,
    month: str,
    input_hash: str,
) -> int:
    cfg = get_settings()
    audit_log = reserve_live_call_budget(
        db,
        tenant_id=tenant_id,
        actor_account_id=actor_account_id,
        provider=provider,
        model=cfg.budget_advisor_model or None,
        base_url=cfg.budget_advisor_base_url or None,
        month=month,
        input_hash=input_hash,
    )
    return audit_log.id


def _complete_live_call(
    db: Session,
    *,
    audit_log_id: int,
    started: float,
    advice: BudgetAdvice | None,
    error_code: str | None,
) -> None:
    try:
        complete_live_call_audit_row(
            db,
            audit_log_id=audit_log_id,
            success=advice is not None and error_code is None,
            error_code=error_code,
            suggestion_count=len(advice.suggestions) if advice is not None else 0,
            duration_ms=int((perf_counter() - started) * 1000),
        )
    except Exception:  # noqa: BLE001 - audit update must not mask result
        db.rollback()


def _advisor_reason_code(advisor: object, *, default: str) -> str:
    reason = getattr(advisor, "last_error_code", None)
    return reason if isinstance(reason, str) and reason else default
