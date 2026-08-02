"""/web dashboard, insights overview, dashboard data, and card settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _amount_segments,
    _base_ctx,
    _dashboard_data_payload,
    _list_ledger_options,
    _minor_amount_label,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    _web_redirect,
    templates,
)
from app.schemas import DashboardCardsUpdateRequest, DashboardCardUpdateRequest
from app.services.dashboard_service import list_dashboard_cards, update_dashboard_cards
from app.services.expense_service import ledger_has_any_expense

router = APIRouter(prefix="/web", tags=["web"])

# 泳道归属是信息架构 (哪些事实属于同一组), 持久化 position 是组内顺序
# (PR #253 P2-1/P2-2): 组内卡片按用户保存的顺序渲染, 空泳道整组不出。
_OVERVIEW_LANE_SPECS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("需处理", "优先处理会影响账面可信度的记录", frozenset({"pending", "recent_uploads"})),
    (
        "本月事实",
        "已入账金额、结构与基础状态",
        frozenset({"monthly_spend", "reports", "backup_status", "device_status"}),
    ),
    ("计划状态", "预算、目标和固定支出的执行情况", frozenset({"budget", "goals", "recurring"})),
)


def _overview_lanes(visible_cards: list[dict]) -> list[dict]:
    """Group persisted-order visible cards into lanes; drop empty lanes."""
    lanes = []
    for title, summary, keys in _OVERVIEW_LANE_SPECS:
        cards = [item for item in visible_cards if item["key"] in keys]
        if cards:
            lanes.append({"title": title, "summary": summary, "cards": cards})
    return lanes


def _overview_amount_views(cards: dict, *, currency_code: str) -> dict:
    """exponent 感知的金额展示投影 (PR #253 P1-1)。

    payload 的 ``*_yuan`` 键固定 /100, 零小数币种 (JPY/KRW) 会错两位;
    这里统一走 C5b-3 的 minor-units 格式化族, 模板不再自己拼币种符号。
    """
    for row in cards["budget_top"]:
        row["overspent_label"] = _minor_amount_label(
            row["overspent_cents"],
            currency_code,
        )
    return {
        "hero_amount": _amount_segments(
            cards["total_amount_cents"],
            currency_code,
        ),
        "delta_amount_label": _minor_amount_label(
            cards["delta_amount_cents"],
            currency_code,
        ),
        "previous_total_label": _minor_amount_label(
            cards["previous_total_amount_cents"],
            currency_code,
        ),
        "budget_remaining_label": _minor_amount_label(
            cards["budget_remaining_cents"],
            currency_code,
        ),
    }


@router.get("/overview", response_class=HTMLResponse)
def web_overview(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """洞察域首页 (218-D S2, 移植自产品矿 /web/overview)。

    数据全部复用既有装配: ``_dashboard_data_payload`` (本月支出/待办/预算/目标/
    固定支出/备份/设备卡片 + 分类占比) + ``ledger_has_any_expense`` (空账本引导
    判定, 与 /web 首页同一口径), 不发明新聚合。只读页——无任何写入口径,
    viewer 与 owner 看到同一份事实。
    """
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="总览",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    payload = _dashboard_data_payload(db, selected_id, include_trend=False)
    cards = payload["cards"]
    category_share = payload["category_share"]
    visible_cards = [item for item in cards["layout"] if item["visible"]]
    ctx["cards"] = cards
    ctx["category_share"] = category_share
    ctx["has_any_expense"] = ledger_has_any_expense(db, selected_id)
    ctx["overview_lanes"] = _overview_lanes(visible_cards)
    ctx.update(
        _overview_amount_views(
            cards,
            currency_code=ctx["home_currency_code"],
        )
    )
    # P2-3: ~1.1MB ECharts 只在环图真的渲染时才下载 (reports 卡可见且有分类数据)。
    ctx["overview_load_charts"] = bool(category_share) and any(
        item["key"] == "reports" for item in visible_cards
    )
    return templates.TemplateResponse(request=request, name="overview.html", context=ctx)


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
    return _web_redirect("/web/dashboard/cards", selected_id, msg="Dashboard 卡片已保存。")


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
    return _web_redirect("/web/dashboard/cards", selected_id, msg="已恢复默认卡片。")
