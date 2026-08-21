"""Stable facade and dashboard context shared by ``/web`` routes.

Session/ledger mechanics and currency-aware expense formatting live in private
modules.  This module keeps the established import surface used by route and
test consumers while owning the base template and dashboard composition.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.middleware.csrf import csrf_context
from app.money_contract import projection_sum_to_int, projection_values_sum_to_int
from app.routes._web_dashboard_calculations import (
    dashboard_month_delta,
    previous_month_string,
    recurring_status_counts,
)
from app.routes._web_money_views import (
    _amount_segments,
    _amount_yuan,
    _calendar_date_label,
    _confirmed_by_day,
    _confirmed_source_breakdown,
    _currency_input_view,
    _currency_symbol,
    _expense_amount_labels,
    _expense_time_local_input,
    _expense_view,
    _home_amount_label,
    _minor_amount_label,
    _minor_amount_value,
    _month_display_label,
    _trend14_amounts,
)
from app.routes._web_session_common import (
    LedgerOption,
    LocalOnly,
    _list_ledger_options,
    _require_local,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _safe_same_site_redirect_path,
    _selected_option,
    _web_redirect,
    _with_ledger,
    parse_form_row_version_token,
)
from app.services import dataset_backup_inventory, web_stats_service
from app.services.budget_service import get_monthly_budget
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import minor_amount_major_number, minor_amount_value, minor_unit_digits
from app.services.dashboard_service import list_dashboard_cards
from app.services.goal_service import list_goals
from app.services.insights_service import unclaimed_recurring_candidate_count
from app.services.spending_contract_service import default_accounting_timezone_name
from app.services.stats_service import monthly_stats
from app.services.time_service import current_month, now_utc
from app.services.time_service import to_iso as _datetime_to_iso
from app.version import BACKEND_VERSION, STATIC_ASSET_VERSION

__all__ = [
    "LocalOnly",
    "LedgerOption",
    "_amount_segments",
    "_amount_yuan",
    "_base_ctx",
    "_calendar_date_label",
    "_confirmed_by_day",
    "_confirmed_source_breakdown",
    "_currency_input_view",
    "_expense_amount_labels",
    "_expense_time_local_input",
    "_expense_view",
    "_home_amount_label",
    "_list_ledger_options",
    "_minor_amount_label",
    "_minor_amount_value",
    "_month_display_label",
    "_require_local",
    "_require_selected_ledger_write",
    "_resolve_selected_ledger_id",
    "_safe_same_site_redirect_path",
    "_selected_option",
    "_sidebar_counts",
    "_trend14_amounts",
    "_web_redirect",
    "_with_ledger",
    "parse_form_row_version_token",
    "templates",
]

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "web"
templates = Jinja2Templates(
    directory=str(_TEMPLATES_DIR),
    context_processors=[csrf_context],
)
templates.env.filters["to_iso"] = _datetime_to_iso

_VALID_UI_THEMES = {"paper", "mono", "midnight"}


def _read_ui_theme(request: Request) -> str:
    raw = request.cookies.get("ui_theme")
    if raw in _VALID_UI_THEMES:
        return raw
    return "paper"


def _sidebar_counts(db: Session, ledger_id: str) -> tuple[int, int]:
    return web_stats_service.sidebar_counts(db, ledger_id)


def _base_ctx(
    request: Request,
    *,
    db: Session,
    options: list[LedgerOption],
    selected_ledger_id: str,
    page_title: str | None = None,
    show_month_picker: bool = False,
    selected_month: str | None = None,
    sidebar_counts: tuple[int, int] | None = None,
) -> dict:
    selected = _selected_option(options, selected_ledger_id)
    pending_count, suspected_count = sidebar_counts or (0, 0)
    home = require_runtime_home_currency_code(db)
    return {
        "backend_version": BACKEND_VERSION,
        "asset_version": STATIC_ASSET_VERSION,
        "request": request,
        "ledger_options": options,
        "selected_ledger_id": selected_ledger_id,
        "selected_ledger_name": selected.name,
        "selected_ledger_role": selected.role,
        "selected_ledger_is_default": selected.is_default,
        "is_viewer": selected.role == "viewer",
        "can_write": selected.role in ("owner", "member"),
        "page_title": page_title,
        "ui_theme": _read_ui_theme(request),
        "show_month_picker": show_month_picker,
        "selected_month": selected_month,
        "pending_count": pending_count,
        "suspected_duplicate_count": suspected_count,
        "home_currency_code": home,
        "home_currency_symbol": _currency_symbol(home),
        "home_currency_minor_digits": minor_unit_digits(home),
        "home_amount_value": lambda amount: minor_amount_value(amount, home),
        "currency_input": _currency_input_view(home),
    }


def _budget_top_rows(budget, *, currency_code: str) -> list[dict]:
    rows = sorted(
        budget.category_budgets,
        key=lambda category: category.spent_amount_cents,
        reverse=True,
    )[:3]
    out: list[dict] = []
    for category in rows:
        limit_cents = projection_sum_to_int(
            category.amount_cents,
            label="web.budget_limit",
        )
        spent_cents = projection_sum_to_int(
            category.spent_amount_cents,
            label="web.budget_spent",
        )
        overspent_cents = projection_sum_to_int(
            category.overspent_amount_cents,
            label="web.budget_overspent",
        )
        percent = (
            (spent_cents * 100 + limit_cents // 2) // limit_cents
            if limit_cents > 0
            else 0
        )
        out.append(
            {
                "name": category.category,
                "limit_yuan": _amount_yuan(limit_cents, currency_code),
                "spent_yuan": _amount_yuan(spent_cents, currency_code),
                "overspent_yuan": _amount_yuan(overspent_cents, currency_code),
                "overspent_cents": overspent_cents,
                "percent": min(percent, 100),
                "is_over": category.overspent_amount_cents > 0,
            }
        )
    return out


def _goals_top_rows(goals, *, currency_code: str) -> list[dict]:
    rows = sorted(goals, key=lambda goal: goal.progress_percent, reverse=True)[:3]
    return [
        {
            "name": goal.name,
            "target_yuan": _amount_yuan(
                projection_sum_to_int(
                    goal.target_amount_cents,
                    label="web.goal_target",
                ),
                currency_code,
            ),
            "spent_yuan": _amount_yuan(
                projection_sum_to_int(
                    goal.spent_amount_cents,
                    label="web.goal_spent",
                ),
                currency_code,
            ),
            "percent": min(int(goal.progress_percent), 100),
            "state": goal.progress_state,
        }
        for goal in rows
    ]


def _dashboard_budget_goals_block(
    budget,
    goals,
    *,
    currency_code: str,
) -> dict:
    goal_risk_count = sum(
        1
        for goal in goals
        if goal.progress_state in {"near_limit", "over_limit"}
    )
    return {
        "budget_configured": budget.configured,
        "budget_total_yuan": _amount_yuan(
            projection_sum_to_int(
                budget.total_amount_cents,
                label="web.budget_total",
            ),
            currency_code,
        ),
        "budget_remaining_yuan": _amount_yuan(
            projection_sum_to_int(
                budget.remaining_amount_cents,
                label="web.budget_remaining",
            ),
            currency_code,
        ),
        "budget_remaining_cents": projection_sum_to_int(
            budget.remaining_amount_cents,
            label="web.budget_remaining",
        ),
        "budget_overspent_yuan": _amount_yuan(
            projection_sum_to_int(
                budget.overspent_amount_cents,
                label="web.budget_overspent",
            ),
            currency_code,
        ),
        "budget_is_over": budget.remaining_amount_cents < 0,
        "budget_top": _budget_top_rows(budget, currency_code=currency_code),
        "goals_count": len(goals),
        "goals_risk_count": goal_risk_count,
        "goals_top": _goals_top_rows(goals, currency_code=currency_code),
    }


def _dashboard_status_counts_block(db: Session, ledger_id: str, now) -> dict:
    week_ago = now - timedelta(days=7)
    backup = dataset_backup_inventory.latest_published_backup_record()
    backup_age_days = None
    if backup is not None:
        backup_age_days = max(
            0,
            (now.astimezone() - backup.created_at).days,
        )
    return {
        "recent_count": web_stats_service.recent_expense_count(
            db,
            ledger_id,
            week_ago,
        ),
        "recent_confirmed_count": web_stats_service.recent_confirmed_expense_count(
            db,
            ledger_id,
            week_ago,
        ),
        "active_device_count": web_stats_service.active_device_count(db, ledger_id),
        "backup_available": backup is not None,
        "backup_age_days": backup_age_days,
    }


def _dashboard_cards(
    db: Session,
    ledger_id: str,
    *,
    currency_code: str | None = None,
) -> dict:
    home = currency_code or require_runtime_home_currency_code(db)
    quality = web_stats_service.pending_quality_counts(db, ledger_id)
    timezone_name = default_accounting_timezone_name()
    month = current_month(timezone_name)
    stats = monthly_stats(db, month, ledger_id)
    prev_month = previous_month_string(month)
    prev_stats = monthly_stats(db, prev_month, ledger_id) if prev_month else None
    active_recurring, paused_recurring = recurring_status_counts(db, ledger_id)
    budget = get_monthly_budget(
        db,
        tenant_id=ledger_id,
        month=month,
        timezone_name=timezone_name,
    )
    goals = list_goals(
        db,
        tenant_id=ledger_id,
        month=month,
        timezone_name=timezone_name,
    )
    now = now_utc()
    layout = list_dashboard_cards(db, tenant_id=ledger_id, surface="web")
    recurring_card_visible = any(
        item.visible and item.key == "recurring"
        for item in layout.items
    )
    candidate_count = (
        unclaimed_recurring_candidate_count(db, tenant_id=ledger_id)
        if recurring_card_visible
        else 0
    )
    current_total, prev_total, delta_amount, delta_direction, delta_percent = (
        dashboard_month_delta(stats, prev_stats)
    )
    return {
        "layout": [
            {
                "key": item.key,
                "title": item.title,
                "visible": item.visible,
                "position": item.position,
            }
            for item in layout.items
        ],
        **quality,
        "month": month,
        "total_amount_yuan": _amount_yuan(current_total, home),
        "total_amount_cents": current_total,
        "total_amount_segments": _amount_segments(current_total, home),
        "confirmed_count": int(stats["count"]),
        "previous_month": prev_month,
        "previous_total_amount_yuan": _amount_yuan(prev_total, home),
        "previous_total_amount_cents": prev_total,
        "delta_amount_yuan": _amount_yuan(abs(delta_amount), home),
        "delta_amount_cents": abs(delta_amount),
        "delta_direction": delta_direction,
        "delta_percent": delta_percent,
        "recurring_active_count": active_recurring,
        "recurring_paused_count": paused_recurring,
        "recurring_candidate_count": candidate_count,
        **_dashboard_budget_goals_block(
            budget,
            goals,
            currency_code=home,
        ),
        **_dashboard_status_counts_block(db, ledger_id, now),
    }


def _dashboard_category_share(
    db: Session,
    selected_id: str,
    *,
    currency_code: str | None = None,
) -> list[dict]:
    timezone_name = default_accounting_timezone_name()
    month = current_month(timezone_name)
    stats = monthly_stats(
        db,
        month,
        selected_id,
        timezone_name=timezone_name,
    )
    home = currency_code or require_runtime_home_currency_code(db)
    by_category = list(stats.get("by_category", []))
    if len(by_category) > 6:
        head, tail = by_category[:5], by_category[5:]
        tail_cents = projection_values_sum_to_int(
            (item["amount_cents"] for item in tail),
            label="web.category_tail",
        )
        tail_count = sum(int(item["count"]) for item in tail)
        merged_into_existing = False
        for item in head:
            if item["category"] == "其他":
                item["amount_cents"] = projection_sum_to_int(
                    projection_sum_to_int(
                        item["amount_cents"],
                        label="web.category_other",
                    )
                    + tail_cents,
                    label="web.category_other_merged",
                )
                item["count"] = int(item["count"]) + tail_count
                merged_into_existing = True
                break
        by_category = (
            head
            if merged_into_existing
            else [
                *head,
                {
                    "category": "其他",
                    "amount_cents": tail_cents,
                    "count": tail_count,
                },
            ]
        )
    rows = []
    for item in by_category:
        amount_minor = projection_sum_to_int(
            item["amount_cents"],
            label="web.category_share",
        )
        rows.append(
            {
                "name": item["category"],
                "amount_yuan": minor_amount_major_number(amount_minor, home),
                "amount_cents": amount_minor,
                "amount_label": _minor_amount_label(amount_minor, home),
                "amount_major": minor_amount_major_number(amount_minor, home),
                "amount_major_text": minor_amount_value(amount_minor, home),
                "count": int(item["count"]),
            }
        )
    return rows


def _dashboard_data_payload(
    db: Session,
    selected_id: str,
    *,
    include_trend: bool = True,
) -> dict:
    home = require_runtime_home_currency_code(db)
    cards = _dashboard_cards(db, selected_id, currency_code=home)
    return {
        "selected_ledger_id": selected_id,
        "month": cards["month"],
        "cards": cards,
        "visible_layout": [
            item for item in cards["layout"] if item["visible"]
        ],
        "trend14": (
            _trend14_amounts(db, selected_id, currency_code=home)
            if include_trend
            else []
        ),
        "category_share": _dashboard_category_share(
            db,
            selected_id,
            currency_code=home,
        ),
    }
