"""Closed-vocabulary presentation labels for the Desktop product projection."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.schemas._desktop_product import DesktopProductField
from app.services.currency_common import minor_amount_label

_STATUS_LABELS = {
    "pending": "待处理",
    "confirmed": "已确认",
    "open": "进行中",
    "cleared": "已结清",
    "voided": "已作废",
    "active": "生效中",
    "paused": "已暂停",
    "archived": "已归档",
    "configured": "已配置",
    "unconfigured": "未配置",
    "healthy": "正常",
    "attention": "需留意",
    "empty": "无数据",
}
_DEBT_KIND_LABELS = {
    "unspecified": "未分类",
    "revolving": "循环周转",
    "installment": "分期还款",
    "one_off": "一次性借款",
}
_GOAL_PROGRESS_LABELS = {
    "not_started": "未开始",
    "on_track": "正常",
    "near_limit": "接近上限",
    "over_limit": "已超限",
    "archived": "已归档",
}
_GOAL_STATUS_LABELS = {
    "active": "生效中",
    "archived": "已归档",
}
_INCOME_SOURCE_LABELS = {
    "salary": "工资",
    "bonus": "奖金",
    "freelance": "副业 / 接单",
    "rental": "租金",
    "other": "其它",
}
_INCOME_FREQUENCY_LABELS = {
    "monthly": "每月固定",
    "one_time": "实际到账",
}
_MEMBER_DEBT_ROLE_LABELS = {
    True: "你帮我垫的",
    False: "我帮你垫的",
    None: "他们之间的一件事",
}
_EXTERNAL_DEBT_ROLE_LABELS = {
    True: "我的应付",
    False: "我的应收",
    None: "往来事实",
}


def _closed_label(value: Any, labels: dict[str, str], fallback: str) -> str:
    key = str(value or "").strip().casefold()
    return labels.get(key, fallback)


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _temporal_precision(value: date | datetime | None) -> str | None:
    if isinstance(value, datetime):
        return "instant"
    if isinstance(value, date):
        return "date"
    return None


def _text(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    cleaned = str(value).strip()
    return cleaned or fallback


def _field(
    label: str,
    value: Any,
    fallback: str = "—",
) -> DesktopProductField:
    return DesktopProductField(label=label, value=_text(value, fallback))


def _money(amount_minor: int | None, currency_code: str) -> str:
    if amount_minor is None:
        return "—"
    return minor_amount_label(amount_minor, currency_code)


def _debt_kind_label(value: Any) -> str:
    return _closed_label(value, _DEBT_KIND_LABELS, "未分类")


def _debt_role_label(
    counterparty_type: Any,
    viewer_is_debtor: bool | None,
) -> str:
    labels = (
        _MEMBER_DEBT_ROLE_LABELS
        if str(counterparty_type or "").strip().casefold() == "member"
        else _EXTERNAL_DEBT_ROLE_LABELS
    )
    return labels[viewer_is_debtor]


def _goal_progress_label(value: Any) -> str:
    return _closed_label(value, _GOAL_PROGRESS_LABELS, "进度待确认")


def _goal_status_label(value: Any) -> str:
    return _closed_label(value, _GOAL_STATUS_LABELS, "状态待确认")


def _income_source_label(value: Any) -> str:
    return _closed_label(value, _INCOME_SOURCE_LABELS, "其它")


def _income_frequency_label(value: Any) -> str:
    return _closed_label(value, _INCOME_FREQUENCY_LABELS, "到账安排待确认")
