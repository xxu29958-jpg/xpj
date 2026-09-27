"""v1.1 budget advisor API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.money_contract import MoneySign, parse_canonical_money_minor
from app.schemas import (
    BudgetAdviceDto,
    BudgetAdviseRequest,
    BudgetAdviseResponse,
    BudgetAdvisorStatusResponse,
    BudgetSuggestionDto,
    DiscretionaryResponse,
)
from app.schemas._budget_advisor import BudgetInputsResponse
from app.schemas._money import NonNegativeMoneyMinorText
from app.services.budget_advisor_service import (
    BudgetAdvice,
    advisor_status_for_tenant,
    read_budget_inputs,
    run_budget_advisor,
)
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.ledger_calendar_service import current_ledger_month
from app.tenants import AuthContext

router = APIRouter(prefix="/api/budget", tags=["budget-advisor"])


@router.get("/discretionary", response_model=DiscretionaryResponse)
def get_discretionary(
    month: str | None = Query(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Accounting month used for one-time income.",
    ),
    savings_target_cents: Annotated[NonNegativeMoneyMinorText | None, Query()] = None,
    reserved_buffer_cents: Annotated[NonNegativeMoneyMinorText | None, Query()] = None,
    home_currency_code: str | None = Query(default=None, pattern=r"^[A-Z]{3}$"),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DiscretionaryResponse:
    # Keep the existing single-parameter calculator usable; omitted amounts
    # remain zero for this legacy trial entry. An unparameterized read uses
    # the saved arrangement instead.
    trial = savings_target_cents is not None or reserved_buffer_cents is not None
    savings_target = _trial_minor(savings_target_cents or "0") if trial else None
    reserved_buffer = _trial_minor(reserved_buffer_cents or "0") if trial else None
    month_label = month or current_ledger_month(db, ledger_id=auth.tenant_id)
    projection = read_budget_inputs(
        db, tenant_id=auth.tenant_id, month=month_label,
        home_currency_code=(home_currency_code or require_runtime_home_currency_code(db)) if trial else home_currency_code,
        savings_target_cents=savings_target,
        reserved_buffer_cents=reserved_buffer,
    )
    return DiscretionaryResponse.model_validate(projection.breakdown)


@router.get("/advisor/inputs", response_model=BudgetInputsResponse)
def get_advisor_inputs(
    month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    timezone: str | None = Query(default=None),
    home_currency_code: str | None = Query(default=None, pattern=r"^[A-Z]{3}$"),
    savings_target_cents: Annotated[NonNegativeMoneyMinorText | None, Query()] = None,
    reserved_buffer_cents: Annotated[NonNegativeMoneyMinorText | None, Query()] = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BudgetInputsResponse:
    projection = read_budget_inputs(db, tenant_id=auth.tenant_id, month=month,
        home_currency_code=home_currency_code, timezone_name=timezone or "Asia/Shanghai",
        savings_target_cents=_trial_minor(savings_target_cents), reserved_buffer_cents=_trial_minor(reserved_buffer_cents))
    return BudgetInputsResponse.model_validate(projection)


@router.post("/advise", response_model=BudgetAdviseResponse)
def post_advise(
    payload: BudgetAdviseRequest,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BudgetAdviseResponse:
    result = run_budget_advisor(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        actor_role=auth.role,
        month=payload.month,
        timezone_name=payload.timezone or "Asia/Shanghai",
        home_currency_code=payload.home_currency_code,
        savings_target_cents=payload.savings_target_cents,
        reserved_buffer_cents=payload.reserved_buffer_cents,
    )
    return BudgetAdviseResponse(
        advice=_advice_to_dto(result.advice),
        home_currency_code=result.home_currency_code,
        provider_name=result.provider_name,
        reason_code=result.reason_code,
        inputs=BudgetInputsResponse.model_validate(result.inputs),
    )


@router.get("/advisor/status", response_model=BudgetAdvisorStatusResponse)
def get_advisor_status(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BudgetAdvisorStatusResponse:
    status = advisor_status_for_tenant(db, tenant_id=auth.tenant_id, actor_role=auth.role)
    return BudgetAdvisorStatusResponse(
        provider=status.provider,
        model=status.model,
        owner_confirmed=status.owner_confirmed,
        is_live=status.is_live,
        needs_confirmation=status.needs_confirmation,
        configuration_valid=status.configuration_valid,
        can_request=status.can_request,
        unavailable_reason=status.unavailable_reason,
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


def _trial_minor(value: str | None) -> int | None:
    return None if value is None else parse_canonical_money_minor(value, sign=MoneySign.NONNEGATIVE,
        label="budget_inputs.reserve_amount")
