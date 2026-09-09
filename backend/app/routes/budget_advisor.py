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
from app.services.spending_contract_service import current_accounting_month
from app.tenants import AuthContext

router = APIRouter(prefix="/api/budget", tags=["budget-advisor"])


@router.get("/discretionary", response_model=DiscretionaryResponse)
def get_discretionary(
    month: str | None = Query(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Accounting month used for one-time income.",
    ),
    savings_target_cents: Annotated[NonNegativeMoneyMinorText, Query()] = "0",
    reserved_buffer_cents: Annotated[NonNegativeMoneyMinorText, Query()] = "0",
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DiscretionaryResponse:
    savings_target = parse_canonical_money_minor(
        savings_target_cents,
        sign=MoneySign.NONNEGATIVE,
        label="budget_discretionary.savings_target_cents",
    )
    reserved_buffer = parse_canonical_money_minor(
        reserved_buffer_cents,
        sign=MoneySign.NONNEGATIVE,
        label="budget_discretionary.reserved_buffer_cents",
    )
    month_label = month or current_accounting_month()
    projection = read_budget_inputs(
        db, tenant_id=auth.tenant_id, month=month_label,
        savings_target_cents=savings_target,
        reserved_buffer_cents=reserved_buffer,
    )
    return DiscretionaryResponse.model_validate(projection.breakdown)


@router.get("/advisor/inputs", response_model=BudgetInputsResponse)
def get_advisor_inputs(
    month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    timezone: str | None = Query(default=None),
    home_currency_code: str | None = Query(default=None, pattern=r"^[A-Z]{3}$"),
    savings_target_cents: Annotated[NonNegativeMoneyMinorText, Query()] = "0",
    reserved_buffer_cents: Annotated[NonNegativeMoneyMinorText, Query()] = "0",
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BudgetInputsResponse:
    projection = read_budget_inputs(db, tenant_id=auth.tenant_id, month=month,
        home_currency_code=home_currency_code, timezone_name=timezone or "Asia/Shanghai",
        savings_target_cents=parse_canonical_money_minor(savings_target_cents, sign=MoneySign.NONNEGATIVE,
            label="budget_inputs.savings_target_cents"),
        reserved_buffer_cents=parse_canonical_money_minor(reserved_buffer_cents, sign=MoneySign.NONNEGATIVE,
            label="budget_inputs.reserved_buffer_cents"))
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
    )
    return BudgetAdviseResponse(
        advice=_advice_to_dto(result.advice),
        home_currency_code=result.home_currency_code,
        provider_name=result.provider_name,
        reason_code=result.reason_code,
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
