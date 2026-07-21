"""Form and fact-history presentation helpers for Web Debt routes."""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from sqlalchemy.orm import Session

from app.routes.web_common import (
    _base_ctx,
    _home_amount_label,
    _sidebar_counts,
)
from app.services.currency_common import (
    currency_input_metadata,
    currency_symbol,
    supported_currency_codes,
)
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import now_utc

_DEBT_KIND_LABELS = {
    "unspecified": "暂不分类",
    "revolving": "循环还款",
    "installment": "分期还款",
    "one_off": "一次还清",
}
_DEBT_KIND_OPTIONS = tuple(_DEBT_KIND_LABELS.items())
_CURRENCY_ORDER = ("CNY", "USD", "EUR", "GBP", "JPY", "HKD", "KRW")


def _debt_create_values(
    *,
    home_currency: str,
    values: dict[str, str] | None = None,
) -> dict[str, str]:
    defaults = {
        "direction": "i_owe",
        "counterparty_label": "",
        "amount_major": "",
        "currency_code": home_currency,
        "event_time": now_utc().astimezone(accounting_zone()).strftime("%Y-%m-%dT%H:%M"),
        "debt_kind": "unspecified",
        "installment_count": "",
        "installment_period_months": "",
        "idempotency_key": str(uuid4()),
    }
    if values:
        defaults.update(values)
    return defaults


def _debt_create_context(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    values: dict[str, str] | None = None,
    error: str | None = None,
) -> dict:
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="新增外部往来",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    supported = supported_currency_codes()
    ctx["form_values"] = _debt_create_values(
        home_currency=ctx["home_currency_code"],
        values=values,
    )
    ctx["form_error"] = error
    ctx["debt_kind_options"] = _DEBT_KIND_OPTIONS
    ctx["currency_options"] = [
        {
            **currency_input_metadata(code),
            "label": f"{code} · {currency_symbol(code)}",
        }
        for code in _CURRENCY_ORDER
        if code in supported
    ]
    return ctx


def _repayment_fact_view(fact, *, home_currency: str) -> dict:
    original_label = None
    if fact.original_currency_code and fact.original_amount_minor is not None:
        original_label = _home_amount_label(
            fact.original_amount_minor,
            fact.original_currency_code,
        )
    void_fact = fact.void_fact
    return {
        "public_id": fact.public_id,
        "amount_label": _home_amount_label(fact.amount_cents, home_currency),
        "original_label": original_label,
        "paid_at_text": fact.paid_at.astimezone(accounting_zone()).strftime("%Y-%m-%d %H:%M"),
        "status": fact.status,
        "status_label": "已生效" if fact.status == "active" else "已撤销",
        "void_reason": void_fact.reason if void_fact is not None else None,
        "voided_at_text": (
            void_fact.created_at.astimezone(accounting_zone()).strftime("%Y-%m-%d %H:%M")
            if void_fact is not None
            else None
        ),
        "void_idempotency_key": str(uuid4()),
    }
