"""Browser presentation model for refund, chargeback, and reversal facts."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.routes._web_money_views import _minor_amount_label
from app.schemas import ExpenseFactBundleResponse
from app.services.currency_common import currency_input_metadata, minor_amount_value
from app.services.expense_offset_service import expense_fact_bundle
from app.services.spending_contract_service import (
    accounting_datetime_label,
    accounting_zone,
)
from app.services.time_service import now_utc

_KIND_LABELS = {
    "refund": "商家退款",
    "chargeback": "银行拒付",
    "reversal": "冲销",
}
_CHANGE_LABELS = {
    "created": "已登记",
    "correction": "已更正",
    "void": "已撤销",
}
_STATUS_LABELS = {
    "confirmed": "已确认",
    "partially_refunded": "部分退回",
    "fully_refunded": "已全部退回",
    "reversed": "已冲销",
}


def _active_offset_rows(bundle: ExpenseFactBundleResponse) -> list[dict[str, object]]:
    return [
        {
            "public_id": offset.public_id,
            "kind": offset.kind,
            "kind_label": _KIND_LABELS[offset.kind],
            "amount_label": _minor_amount_label(
                offset.original_amount_minor,
                offset.original_currency_code,
            ),
            "home_amount_label": _minor_amount_label(
                offset.amount_cents,
                offset.home_currency_code,
            ),
            "accounting_date": offset.accounting_date.isoformat(),
            "reason": offset.reason,
            "row_version": offset.row_version,
            "void_idempotency_key": str(uuid4()),
        }
        for offset in bundle.active_offsets
    ]


def _recent_history_rows(bundle: ExpenseFactBundleResponse) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for revision in bundle.recent_history:
        actor = " · ".join(
            part
            for part in (revision.actor_account_name, revision.actor_device_name)
            if part
        )
        rows.append(
            {
                "kind_label": _CHANGE_LABELS[revision.change_kind],
                "reason": revision.reason,
                "when": accounting_datetime_label(revision.created_at),
                "actor": actor,
            }
        )
    return rows


def _summary_view(bundle: ExpenseFactBundleResponse) -> dict[str, object]:
    root = bundle.root
    summary = bundle.financial_summary
    original_code = root.original_currency_code
    home_code = root.home_currency
    return {
        "status": summary.status,
        "status_label": _STATUS_LABELS[summary.status],
        "gross_original_label": _minor_amount_label(
            summary.gross_original_minor,
            original_code,
        ),
        "gross_home_label": _minor_amount_label(summary.gross_home_amount_cents, home_code),
        "refunded_original_label": _minor_amount_label(
            summary.active_refunded_original_minor,
            original_code,
        ),
        "remaining_original_label": _minor_amount_label(
            summary.remaining_refundable_original_minor,
            original_code,
        ),
        "remaining_original_value": minor_amount_value(
            summary.remaining_refundable_original_minor,
            original_code,
        ),
        "lineage_net_label": _minor_amount_label(summary.lineage_home_net_cents, home_code),
        "fx_difference_label": (
            _minor_amount_label(summary.fx_difference_cents, home_code)
            if summary.fx_difference_cents
            else ""
        ),
    }


def _relationship_view(bundle: ExpenseFactBundleResponse) -> dict[str, object]:
    impacts = bundle.relationship_impacts
    home_code = bundle.root.home_currency
    return {
        "cancelled_count": len(impacts.pending_invites_cancelled),
        "accepted": [
            {
                "receiver_display_name": impact.receiver_display_name or "家庭成员",
                "original_share_label": _minor_amount_label(
                    impact.original_agreed_share_home_minor,
                    home_code,
                ),
                "suggested_share_label": _minor_amount_label(
                    impact.suggested_net_share_home_minor,
                    home_code,
                ),
            }
            for impact in impacts.accepted_impacts
        ],
    }


def offset_fact_view(
    bundle: ExpenseFactBundleResponse,
    *,
    can_write: bool,
) -> dict[str, object]:
    root = bundle.root
    summary = bundle.financial_summary
    return {
        "offset_summary": _summary_view(bundle),
        "offset_currency_input": currency_input_metadata(root.original_currency_code),
        "active_offsets": _active_offset_rows(bundle),
        "offset_recent_history": _recent_history_rows(bundle),
        "offset_relationship_impacts": _relationship_view(bundle),
        "offset_can_write": can_write,
        "offset_can_create_refund": (
            can_write and summary.status not in {"fully_refunded", "reversed"}
        ),
        "offset_can_reverse": can_write and summary.status == "confirmed",
        "offset_reversed": summary.status == "reversed",
        "offset_form": {
            "open": False,
            "kind": "refund",
            "original_amount": "",
            "accounting_date": now_utc().astimezone(accounting_zone()).date().isoformat(),
            "reason": "",
            "expected_row_version": root.row_version,
            "idempotency_key": str(uuid4()),
            "error": "",
            "conflict": False,
        },
        "offset_void_form": {
            "open": False,
            "target_public_id": "",
            "void_reason": "",
            "expected_row_version": "",
            "idempotency_key": str(uuid4()),
            "error": "",
            "conflict": False,
        },
    }


def expense_offset_fact_view(
    db: Session,
    tenant_id: str,
    expense_id: int,
    can_write: bool,
) -> dict[str, object]:
    bundle = expense_fact_bundle(db, tenant_id=tenant_id, expense_id=expense_id)
    return offset_fact_view(bundle, can_write=can_write)
