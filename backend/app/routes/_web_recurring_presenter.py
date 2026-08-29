"""Pure presenter and form helpers for the /web recurring page.

View projections, hero aggregation, candidate review prefill, form parsing and
conflict-guidance presentation. No request routing or DB access lives here —
``web_recurring.py`` owns the routes and page assembly.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from urllib.parse import urlencode
from uuid import uuid4

from app.errors import AppError
from app.money_contract import projection_sum_to_int
from app.routes.web_common import _amount_yuan, _with_ledger
from app.services.currency_common import major_amount_to_minor
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import ensure_utc

# ── view projections ─────────────────────────────────────────────────────────


def status_label(status: str) -> str:
    return {
        "active": "活跃",
        "paused": "暂停",
        "archived": "归档",
    }.get(status, status)


def anomaly_label(status: str) -> str:
    return {
        "higher_than_average": "本月偏高",
        "none": "正常",
    }.get(status, status)


def local_date_iso(value: datetime | None) -> str:
    """Render an observed timestamp as an accounting-timezone calendar date."""
    aware = ensure_utc(value)
    if aware is None:
        return ""
    return aware.astimezone(accounting_zone()).date().isoformat()


def item_view(item, anomaly, *, currency_code: str) -> dict:
    observed = item.occurrence_count > 0
    return {
        "public_id": item.public_id,
        "merchant": item.merchant_name,
        "baseline_amount_yuan": _amount_yuan(item.baseline_amount_cents, currency_code),
        "last_amount_yuan": _amount_yuan(item.last_amount_cents, currency_code),
        # A3 诚实合同: manual + occurrence=0 只能称「每月预计」, 观察来源
        # (上次/最近发生) 仅在 occurrence>0 时渲染。
        "observed": observed,
        "occurrence_count": item.occurrence_count,
        "last_seen_date": local_date_iso(item.last_seen_at) if observed else "",
        "next_expected_date": item.next_expected_date.isoformat() if item.next_expected_date else "",
        "status": item.status,
        "status_label": status_label(item.status),
        # ADR-0041: OCC token (row_version) for the hidden pause/resume form
        # field. Without it parse_form_row_version_token sees "" → the user
        # always hits the "页面已过期" redirect and can never toggle from this page.
        "row_version": item.row_version,
        "anomaly_status": anomaly.anomaly_status,
        "anomaly_label": anomaly_label(anomaly.anomaly_status),
        "current_month_amount_yuan": _amount_yuan(
            anomaly.current_month_amount_cents,
            currency_code,
        ),
        "historical_average_amount_yuan": _amount_yuan(
            anomaly.historical_average_amount_cents,
            currency_code,
        ),
        "amount_delta_percent": anomaly.amount_delta_percent,
        # 每次渲染生成一次: 编辑表单的 durable intent key (ADR-0042)。双击/重试
        # 同一提交 → 服务端 replay; 重新渲染 = 新 intent, 换新键。
        "edit_idempotency_key": uuid4().hex,
    }


def _candidate_amount_cents(candidate: dict) -> int:
    return projection_sum_to_int(
        candidate.get("amount_cents"),
        label="web_recurring.candidate_amount",
    )


def candidate_view(candidate: dict, *, currency_code: str, ledger_id: str) -> dict:
    amount_cents = _candidate_amount_cents(candidate)
    merchant = str(candidate.get("merchant") or "")
    raw_seen = candidate.get("last_seen_at")
    last_seen_date = local_date_iso(raw_seen) if isinstance(raw_seen, datetime) else str(raw_seen or "")[:10]
    # 候选动作 = 进入统一表单的复核模式 (GET)。URL 只带商家定位候选,
    # 观察事实 (金额/次数/最近/置信度) 由服务端扫描重新给出, 不信客户端。
    review_href = "/web/recurring?" + urlencode({"ledger_id": ledger_id, "review": merchant}) + "#add"
    return {
        "merchant": merchant,
        "amount_yuan": _amount_yuan(amount_cents, currency_code),
        "occurrence_count": int(candidate.get("occurrence_count") or 0),
        "last_seen_date": last_seen_date,
        "confidence": str(candidate.get("confidence") or ""),
        "reason": str(candidate.get("reason") or ""),
        "review_href": review_href,
    }


def candidate_review_prefill(candidate: dict, *, currency_code: str) -> dict:
    """统一表单的候选复核模式: 服务端候选扫描的 provenance, 仅用于展示;
    提交时只回传 merchant + amount_cents 定位候选。"""
    amount_cents = _candidate_amount_cents(candidate)
    raw_seen = candidate.get("last_seen_at")
    last_seen_date = local_date_iso(raw_seen) if isinstance(raw_seen, datetime) else str(raw_seen or "")[:10]
    return {
        "merchant": str(candidate.get("merchant") or ""),
        "amount_cents": amount_cents,
        "amount_yuan": _amount_yuan(amount_cents, currency_code),
        "occurrence_count": int(candidate.get("occurrence_count") or 0),
        "last_seen_date": last_seen_date,
        "confidence": str(candidate.get("confidence") or ""),
    }


def hero_view(items, *, currency_code: str) -> dict | None:
    """Hero 只汇总 active 正式项, 与列表状态筛选解耦: 每月合计 + 下一笔到期。"""
    active = [item for item in items if item.status == "active"]
    if not active:
        return None
    total_cents = sum(int(item.baseline_amount_cents) for item in active)
    dated = [item for item in active if item.next_expected_date is not None]
    next_item = min(dated, key=lambda item: (item.next_expected_date, item.merchant_name)) if dated else None
    return {
        "active_count": len(active),
        "monthly_total_yuan": _amount_yuan(total_cents, currency_code),
        "next_due": (
            {
                "merchant": next_item.merchant_name,
                "date": next_item.next_expected_date.isoformat(),
                "amount_yuan": _amount_yuan(next_item.baseline_amount_cents, currency_code),
            }
            if next_item is not None
            else None
        ),
    }


def suggest_next_expected_date(today: date) -> date:
    """创建表单的日期建议: 下月同日 (月末日按目标月夹紧)。仅建议, 可清空。"""
    year, month = today.year, today.month + 1
    if month > 12:
        year, month = year + 1, 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# ── form parsing ─────────────────────────────────────────────────────────────


def parse_baseline_yuan(raw: str, *, currency_code: str) -> int:
    text = (raw or "").strip()
    if not text:
        raise AppError("invalid_request", "请填写每月金额。", status_code=422)
    try:
        result = major_amount_to_minor(text, currency_code)
    except AppError as exc:
        raise AppError(
            "invalid_request",
            "每月金额不是合法金额或超出当前版本可支持范围。",
            status_code=422,
        ) from exc
    if result is None or result <= 0:
        raise AppError("invalid_request", "每月金额必须大于 0。", status_code=422)
    return result


def parse_optional_date(raw: str) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise AppError("invalid_request", "下次预计日期格式不正确。", status_code=422) from exc


# ── conflict guidance (create / edit / candidate-confirm 共用) ────────────────


def _edit_guidance(selected_id: str, public_id: str, item_status: str) -> dict:
    return {
        "href": _with_ledger("/web/recurring", selected_id, status=item_status)
        + (f"#item-{public_id}" if public_id else ""),
        "label": "去编辑现有记录",
    }


def _archived_guidance(selected_id: str, public_id: str) -> dict:
    return {
        "href": _with_ledger("/web/recurring", selected_id, status="archived")
        + (f"#item-{public_id}" if public_id else ""),
        "label": "去归档列表恢复",
    }


def _error_kwargs(message: str) -> dict:
    return {"error_message": message, "error_guidance": None, "open_edit_id": None}


def _duplicate_error_kwargs(
    *,
    selected_id: str,
    public_id: str,
    item_status: str,
    merchant: str | None,
) -> dict:
    name = (merchant or "").strip() or "这个商家"
    if item_status == "archived":
        kwargs = _error_kwargs(f"「{name}」之前已经归档，不能直接再添加一条。")
        kwargs["error_guidance"] = _archived_guidance(selected_id, public_id)
        return kwargs
    kwargs = _error_kwargs(f"「{name}」已经在你的固定支出里，不用再添加一条。")
    kwargs["error_guidance"] = _edit_guidance(selected_id, public_id, item_status)
    kwargs["open_edit_id"] = public_id or None
    return kwargs


def conflict_error_kwargs(
    exc: AppError,
    *,
    selected_id: str,
    merchant: str | None = None,
    stale_page_flash: str,
) -> dict:
    """recurring_item_conflict / recurring_item_archived 409 消费 details
    (public_id/status): active/paused 引导编辑现有项 (渲染时展开其编辑表单),
    archived 引导归档列表恢复; 其余错误诚实呈现。"""
    details = exc.details or {}
    public_id = str(details.get("public_id") or "")
    item_status = str(details.get("status") or "")
    if exc.error == "recurring_item_conflict":
        return _duplicate_error_kwargs(
            selected_id=selected_id,
            public_id=public_id,
            item_status=item_status,
            merchant=merchant,
        )
    kwargs = _error_kwargs(exc.message)
    if exc.error == "recurring_item_archived":
        kwargs["error_message"] = "这条固定支出已归档，不能继续修改；如需继续，请先恢复它。"
        if public_id:
            kwargs["error_guidance"] = _archived_guidance(selected_id, public_id)
    elif exc.error == "state_conflict":
        kwargs["error_message"] = "这条记录刚在别处被修改，已为你刷新最新值，请核对后再保存。"
    elif exc.error in {"idempotency_key_required", "idempotency_key_reused"}:
        kwargs["error_message"] = stale_page_flash
    elif exc.error == "idempotency_key_in_progress":
        kwargs["error_message"] = "这次保存正在处理中，请稍候再试。"
    return kwargs
