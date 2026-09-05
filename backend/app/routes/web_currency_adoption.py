from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.fx_constants import CURRENCY_SYMBOLS
from app.routes.web_common import LocalOnly, _read_ui_theme, templates
from app.services.currency_adoption_service import (
    CurrencyAdoptionPreview,
    adopt_currency_binding_for_installation_owner,
    adoption_preview,
    revalidate_currency_adoption_owner,
)
from app.tenants import AuthContext
from app.version import BACKEND_VERSION, STATIC_ASSET_VERSION

router = APIRouter(prefix="/web", tags=["web"])

_CONFIRM_REASON = "安装拥有者通过小票夹 Desktop 明确确认历史金额的本位币。"
_CURRENCY_NAMES = {
    "CNY": "人民币",
    "USD": "美元",
    "EUR": "欧元",
    "GBP": "英镑",
    "JPY": "日元",
    "HKD": "港币",
    "KRW": "韩元",
}
_RETRYABLE_ERRORS = {
    "currency_binding_evidence_changed": "核对期间记录发生了变化。已重新检查，请再次确认。",
    "currency_binding_state_conflict": "本位币状态刚刚发生了变化。已重新检查当前结果。",
    "currency_adoption_currency_conflict": "记录之间存在币种矛盾，没有改写任何金额。请先处理系统体检中的冲突。",
    "idempotency_key_in_progress": "上次确认仍在处理，请稍后重新检查结果。",
}


def _desktop_auth(request: Request) -> AuthContext:
    auth = getattr(request.state, "web_session_auth", None)
    if (
        getattr(request.state, "web_session_platform", "") != "desktop"
        or not isinstance(auth, AuthContext)
    ):
        raise AppError("permission_denied", status_code=403)
    return auth


def _evidence_token(evidence_sha256: str) -> str:
    return urlsafe_b64encode(bytes.fromhex(evidence_sha256)).decode("ascii").rstrip("=")


def _decode_evidence_token(token: str) -> str:
    cleaned = token.strip()
    try:
        evidence = urlsafe_b64decode(cleaned + "=" * (-len(cleaned) % 4))
    except (ValueError, TypeError) as exc:
        raise AppError("invalid_request", status_code=422) from exc
    if len(evidence) != 32:
        raise AppError("invalid_request", status_code=422)
    return evidence.hex()


def _currency_options(preview: CurrencyAdoptionPreview) -> list[dict[str, str]]:
    return [
        {
            "code": code,
            "name": _CURRENCY_NAMES[code],
            "symbol": CURRENCY_SYMBOLS[code],
        }
        for code in _CURRENCY_NAMES
        if code in preview.allowed_home_currency_codes
    ]


def _render(
    request: Request,
    preview: CurrencyAdoptionPreview,
    *,
    selected_code: str = "",
    error_message: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    if selected_code not in preview.allowed_home_currency_codes:
        selected_code = preview.configured_home_currency_code or ""
    if selected_code not in preview.allowed_home_currency_codes:
        selected_code = preview.allowed_home_currency_codes[0] if len(preview.allowed_home_currency_codes) == 1 else ""
    return templates.TemplateResponse(
        request=request,
        name="currency_adoption.html",
        status_code=status_code,
        context={
            "asset_version": STATIC_ASSET_VERSION,
            "backend_version": BACKEND_VERSION,
            "ui_theme": _read_ui_theme(request),
            "preview": preview,
            "currency_options": _currency_options(preview),
            "selected_code": selected_code,
            "configured_name": _CURRENCY_NAMES.get(preview.configured_home_currency_code or "", ""),
            "active_name": _CURRENCY_NAMES.get(preview.home_currency_code or "", ""),
            "error_message": error_message,
            "evidence_token": _evidence_token(preview.evidence_sha256),
            "idempotency_key": str(uuid4()),
        },
    )


@router.get("/currency-adoption", response_class=HTMLResponse, include_in_schema=False)
def currency_adoption_page(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    revalidate_currency_adoption_owner(db, _desktop_auth(request))
    return _render(request, adoption_preview(db))


@router.post("/currency-adoption", response_class=HTMLResponse, include_in_schema=False)
def currency_adoption_submit(
    request: Request,
    home_currency_code: str = Form(default=""),
    currency_contract_version: int = Form(),
    expected_state: str = Form(),
    expected_binding_revision: int = Form(),
    evidence_token: str = Form(),
    idempotency_key: UUID = Form(),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    auth = _desktop_auth(request)
    try:
        adopt_currency_binding_for_installation_owner(
            db,
            auth=auth,
            idempotency_key=idempotency_key,
            expected_contract_version=currency_contract_version,
            home_code=home_currency_code,
            expected_state=expected_state,
            expected_revision=expected_binding_revision,
            expected_evidence_sha256=_decode_evidence_token(evidence_token),
            reason=_CONFIRM_REASON,
        )
    except AppError as exc:
        if exc.error == "currency_binding_already_active":
            return RedirectResponse(url="/web/currency-adoption", status_code=303)
        if exc.error not in _RETRYABLE_ERRORS:
            raise
        return _render(
            request,
            adoption_preview(db),
            selected_code=home_currency_code,
            error_message=_RETRYABLE_ERRORS[exc.error],
            status_code=409,
        )
    return RedirectResponse(url="/web/currency-adoption", status_code=303)
