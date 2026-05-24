"""v1.1 budget advisor API.

Two endpoints:

- ``GET /api/budget/discretionary`` — pure arithmetic over the user's
  income plan + recurring outflows + caller-supplied savings buffer.
- ``POST /api/budget/advise`` — assemble an anonymised :class:`BudgetInputs`
  (privacy boundary lives in :mod:`app.services.budget_advisor_service`)
  and hand it to the configured provider. With the default ``empty``
  provider this returns ``advice=null`` cleanly so the UI can render
  "no AI suggestion configured" without ambiguity.
"""

from __future__ import annotations

from time import perf_counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.schemas import (
    BudgetAdviceDto,
    BudgetAdviseRequest,
    BudgetAdviseResponse,
    BudgetAdvisorStatusResponse,
    BudgetSuggestionDto,
    DiscretionaryResponse,
)
from app.services.budget_advisor_service import (
    BudgetAdvice,
    advisor_status_for_tenant,
    build_budget_inputs,
    compute_input_hash,
    get_budget_advisor,
    is_live_provider,
    record_audit_row,
    to_outbound_dict,
)
from app.services.budget_baseline_service import (
    compute_monthly_discretionary,
    total_active_recurring_monthly_cents,
)
from app.services.income_plan_service import total_monthly_income_cents
from app.tenants import AuthContext

router = APIRouter(prefix="/api/budget", tags=["budget-advisor"])


@router.get("/discretionary", response_model=DiscretionaryResponse)
def get_discretionary(
    savings_target_cents: int = Query(default=0, ge=0),
    reserved_buffer_cents: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DiscretionaryResponse:
    """本月可自由支配 = income - fixed - savings - reserved (floored at 0)."""
    income = total_monthly_income_cents(db, tenant_id=auth.tenant_id)
    fixed = total_active_recurring_monthly_cents(db, tenant_id=auth.tenant_id)
    breakdown = compute_monthly_discretionary(
        monthly_income_cents=income,
        fixed_expenses_cents=fixed,
        savings_target_cents=savings_target_cents,
        reserved_buffer_cents=reserved_buffer_cents,
    )
    return DiscretionaryResponse(
        monthly_income_cents=breakdown.monthly_income_cents,
        fixed_expenses_cents=breakdown.fixed_expenses_cents,
        savings_target_cents=breakdown.savings_target_cents,
        reserved_buffer_cents=breakdown.reserved_buffer_cents,
        discretionary_cents=breakdown.discretionary_cents,
    )


@router.post("/advise", response_model=BudgetAdviseResponse)
def post_advise(
    payload: BudgetAdviseRequest,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BudgetAdviseResponse:
    """Build anonymised BudgetInputs → advisor → BudgetAdvice.

    ADR-0036: payload going out only includes the allowed-field surface
    (enforced inside the provider by ``to_outbound_dict`` /
    ``validate_outbound_payload``). The de-anonymisation is the UI's
    job, using the alias resolver on the way back.

    Batch 2: when a live (outbound) provider is configured, the route
    refuses to call unless ``BUDGET_ADVISOR_OWNER_CONFIRMED=true``. Every
    invocation against a live provider also writes one audit row
    capturing provider/model + input hash + success.
    """

    cfg = get_settings()
    provider_name = (cfg.budget_advisor_provider or "empty").strip().lower()
    provider_is_live = is_live_provider(provider_name)
    if provider_is_live and not cfg.budget_advisor_owner_confirmed:
        raise AppError(
            "ai_advisor_not_confirmed",
            "AI 预算助手未经过 owner 显式确认，已禁用。",
            status_code=403,
        )

    inputs = build_budget_inputs(
        db,
        tenant_id=auth.tenant_id,
        month=payload.month,
        timezone_name=payload.timezone or "Asia/Shanghai",
    )

    advisor = get_budget_advisor()
    started = perf_counter()
    advice: BudgetAdvice | None = None
    error_code: str | None = None
    try:
        advice = advisor.advise(inputs)
    except AppError as exc:  # pragma: no cover — providers swallow internally
        error_code = exc.error
        raise
    finally:
        if provider_is_live:
            duration_ms = int((perf_counter() - started) * 1000)
            try:
                outbound = to_outbound_dict(inputs)
                input_hash = compute_input_hash(outbound)
            except Exception:  # noqa: BLE001 — never let audit failure abort
                input_hash = "unknown"
            record_audit_row(
                db,
                tenant_id=auth.tenant_id,
                actor_account_id=auth.account_id,
                provider=provider_name,
                model=cfg.budget_advisor_model or None,
                base_url=cfg.budget_advisor_base_url or None,
                month=payload.month,
                input_hash=input_hash,
                success=advice is not None and error_code is None,
                error_code=error_code,
                suggestion_count=(
                    len(advice.suggestions) if advice is not None else 0
                ),
                duration_ms=duration_ms,
            )
    return BudgetAdviseResponse(
        advice=_advice_to_dto(advice),
        provider_name=provider_name,
    )


@router.get("/advisor/status", response_model=BudgetAdvisorStatusResponse)
def get_advisor_status(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BudgetAdvisorStatusResponse:
    status = advisor_status_for_tenant(db, tenant_id=auth.tenant_id)
    return BudgetAdvisorStatusResponse(
        provider=status.provider,
        model=status.model,
        base_url=status.base_url,
        owner_confirmed=status.owner_confirmed,
        is_live=status.is_live,
        needs_confirmation=status.needs_confirmation,
        last_called_at=status.last_called_at,
        last_success=status.last_success,
        last_error_code=status.last_error_code,
        last_suggestion_count=status.last_suggestion_count,
        last_duration_ms=status.last_duration_ms,
    )


def _advice_to_dto(advice: BudgetAdvice | None) -> BudgetAdviceDto | None:
    if advice is None:
        return None
    return BudgetAdviceDto(
        summary=advice.summary,
        suggestions=[
            BudgetSuggestionDto(
                category=s.category,
                suggested_amount_cents=s.suggested_amount_cents,
                rationale=s.rationale,
            )
            for s in advice.suggestions
        ],
        confidence=advice.confidence,
    )
