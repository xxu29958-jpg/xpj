"""/web dashboard, dashboard data, and dashboard card settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _dashboard_cards,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _trend14_amounts,
    _with_ledger,
    templates,
)
from app.schemas import DashboardCardsUpdateRequest, DashboardCardUpdateRequest
from app.services.dashboard_service import list_dashboard_cards, update_dashboard_cards
from app.services.stats_service import monthly_stats
from app.services.time_service import current_month

router = APIRouter(prefix="/web", tags=["web"])


def _dashboard_category_share(db: Session, selected_id: str) -> list[dict]:
    month = current_month("Asia/Shanghai")
    stats = monthly_stats(db, month, selected_id, timezone_name="Asia/Shanghai")
    return [
        {
            "name": item["category"],
            "amount_yuan": int(item["amount_cents"]) / 100.0,
            "amount_cents": int(item["amount_cents"]),
            "count": int(item["count"]),
        }
        for item in stats.get("by_category", [])[:6]
    ]


def _dashboard_data_payload(db: Session, selected_id: str) -> dict:
    cards = _dashboard_cards(db, selected_id)
    return {
        "selected_ledger_id": selected_id,
        "month": cards["month"],
        "cards": cards,
        "visible_layout": [item for item in cards["layout"] if item["visible"]],
        "trend14": _trend14_amounts(db, selected_id),
        "category_share": _dashboard_category_share(db, selected_id),
    }


@router.get("/dashboard/data", response_class=JSONResponse)
def web_dashboard_data(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> JSONResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return JSONResponse(_dashboard_data_payload(db, selected_id))


def _dashboard_cards_context(db: Session, selected_id: str) -> list[dict]:
    cards = list_dashboard_cards(db, tenant_id=selected_id, surface="web")
    return [
        {
            "key": item.key,
            "title": item.title,
            "visible": item.visible,
            "position": item.position,
        }
        for item in cards.items
    ]


def _dashboard_cards_payload(
    *,
    card_key: list[str],
    card_position: list[int],
    visible_key: list[str],
) -> DashboardCardsUpdateRequest:
    if len(card_key) != len(card_position):
        raise AppError("invalid_request", "卡片顺序数据不完整。", status_code=422)
    visible = set(visible_key)
    seen: set[str] = set()
    cards: list[DashboardCardUpdateRequest] = []
    for key, position in zip(card_key, card_position, strict=True):
        cleaned_key = key.strip()
        if not cleaned_key or cleaned_key in seen:
            raise AppError("invalid_request", "卡片数据不正确。", status_code=422)
        seen.add(cleaned_key)
        cards.append(
            DashboardCardUpdateRequest(
                key=cleaned_key,
                visible=cleaned_key in visible,
                position=position,
            )
        )
    return DashboardCardsUpdateRequest(cards=cards)


@router.get("/dashboard/cards", response_class=HTMLResponse)
def web_dashboard_cards_get(
    request: Request,
    ledger_id: str | None = None,
    msg: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["dashboard_cards"] = _dashboard_cards_context(db, selected_id)
    ctx["message"] = msg
    return templates.TemplateResponse(request=request, name="dashboard_cards.html", context=ctx)


@router.post("/dashboard/cards/save", response_class=HTMLResponse)
def web_dashboard_cards_save(
    request: Request,
    ledger_id: str = Form(default=""),
    card_key: list[str] = Form(default=[]),
    card_position: list[int] = Form(default=[]),
    visible_key: list[str] = Form(default=[]),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    payload = _dashboard_cards_payload(
        card_key=card_key,
        card_position=card_position,
        visible_key=visible_key,
    )
    update_dashboard_cards(db, tenant_id=selected_id, surface="web", payload=payload)
    return RedirectResponse(
        url=_with_ledger("/web/dashboard/cards", selected_id, msg="Dashboard 卡片已保存。"),
        status_code=303,
    )


@router.post("/dashboard/cards/reset", response_class=HTMLResponse)
def web_dashboard_cards_reset(
    request: Request,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    update_dashboard_cards(
        db,
        tenant_id=selected_id,
        surface="web",
        payload=DashboardCardsUpdateRequest(cards=[]),
    )
    return RedirectResponse(
        url=_with_ledger("/web/dashboard/cards", selected_id, msg="已恢复默认卡片。"),
        status_code=303,
    )
