"""Native form recovery through the existing manual-rate command owner."""

from datetime import date
from uuid import uuid4

from fastapi import Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_session_common import resolve_web_actor_account_id
from app.schemas import ExchangeRateRequest
from app.services.currency_common import supported_currency_codes
from app.services.exchange_rate_service import list_exchange_rates, set_exchange_rate_idempotently

_RATE_FIELDS = ("currency_code", "home_currency_code", "rate_date", "rate_to_cny",
    "expected_row_version", "idempotency_key")


async def rate_recovery_form(request: Request) -> dict[str, str]:
    """These debt/refund forms have scalar inputs; keep their original command fields."""
    raw = await request.form()
    return {key: str(value) for key, value in raw.items() if key != "csrf_token"}


def rate_recovery_context(db: Session, selected: str, details: dict[str, object] | None) -> dict[str, str] | None:
    """Only the attempted command's explicit server context can open a rate editor."""
    if not details:
        return None
    source, home, raw_date = (details.get(key) for key in _RATE_FIELDS[:3])
    codes = supported_currency_codes()
    if not isinstance(source, str) or not isinstance(home, str) or not isinstance(raw_date, str):
        return None
    if source not in codes or home not in codes or source == home:
        return None
    try:
        rate_date = date.fromisoformat(raw_date)
    except ValueError:
        return None
    if rate_date.isoformat() != raw_date:
        return None
    rates = list_exchange_rates(db, tenant_id=selected, currency_code=source,
        home_currency_code=home, rate_date=rate_date)
    current = rates[0] if rates else None
    return {"currency_code": source, "home_currency_code": home, "rate_date": raw_date,
        "rate_to_cny": str(current.rate_to_cny) if current else "",
        "expected_row_version": str(current.row_version) if current else "0", "idempotency_key": str(uuid4())}


def submit_recovery_rate(db: Session, request: Request, selected: str, values: dict[str, str],
    *, review_latest: bool = False) -> dict[str, object]:
    """Rate acceptance never claims, refreshes or executes the original command."""
    try:
        if review_latest:
            reviewed = rate_recovery_context(db, selected, values)
            if reviewed is None:
                raise AppError("invalid_request", status_code=422)
            values.update(expected_row_version=reviewed["expected_row_version"],
                idempotency_key=reviewed["idempotency_key"])
            current = reviewed["rate_to_cny"]
            message = (f"当前汇率：1 {reviewed['currency_code']} = {current} {reviewed['home_currency_code']}。"
                if current else "当前尚未保存这一天的汇率。")
            return {"status_code": 200, "message": message + "原输入已保留，请核对后决定是否保存。"}
        version = values["expected_row_version"]
        if not version.isascii() or not version.isdecimal():
            raise AppError("state_conflict", status_code=409)
        payload = ExchangeRateRequest(**{key: values[key] for key in _RATE_FIELDS[:4]},
            expected_row_version=int(version))
        receipt = set_exchange_rate_idempotently(db, tenant_id=selected,
            actor_account_id=resolve_web_actor_account_id(db, request, selected),
            payload=payload, idempotency_key=values["idempotency_key"])
    except (AppError, ValidationError) as exc:
        db.rollback()
        return {"status_code": exc.status_code if isinstance(exc, AppError) else 422,
            "error": exc.message if isinstance(exc, AppError) else "请检查汇率，原输入已保留。",
            "conflict": isinstance(exc, AppError) and exc.error in {
                "state_conflict", "idempotency_key_required", "idempotency_key_reused"}}
    return {"status_code": 200, "saved": True,
        "message": f"已保存 {receipt.currency_code} → {receipt.home_currency_code} · {receipt.rate_date} 的汇率 {receipt.rate_to_cny}。原操作尚未保存，请核对原表单后继续提交。"}
