"""Pure view-model pins for the browser repayment-draft inbox."""

from __future__ import annotations

from datetime import UTC, datetime

import app.services.repayment_draft_command_service as draft_commands
from app.routes.web_repayment_drafts import _audit_row_view
from app.routes.web_repayment_drafts import (
    confirm_repayment_draft_idempotently as route_confirm_draft,
)
from app.services.debt_service import RepaymentDraftAuditRow
from app.services.debt_service._repayment_draft_match import RepaymentMatchCandidate


def test_repayment_draft_route_delegates_to_shared_command() -> None:
    assert route_confirm_draft is draft_commands.confirm_repayment_draft_idempotently


def _row(**overrides) -> RepaymentDraftAuditRow:
    base = {
        "source": "alipay",
        "amount_cents": 20000,
        "home_currency_code": "CNY",
        "merchant_label": "花呗",
        "captured_at": datetime(2026, 6, 18, 4, 0, tzinfo=UTC),
        "status": "pending",
        "linked_debt_label": None,
        "has_suggestion": False,
        "suggested_debt_label": None,
    }
    base.update(overrides)
    return RepaymentDraftAuditRow(**base)


def test_view_pending_with_suggestion() -> None:
    view = _audit_row_view(
        _row(
            has_suggestion=True,
            suggested_debt_label="花呗",
            suggested_debt_public_id="debt-1",
            target_debts=(
                RepaymentMatchCandidate(
                    public_id="debt-1",
                    counterparty_label="花呗",
                    remaining_amount_cents=50000,
                    row_version=7,
                ),
            ),
        )
    )
    assert view["status_label"] == "待确认"
    assert view["status_tone"] == ""
    assert view["provenance"] == "建议还到「花呗」"
    assert view["recede"] is False
    assert "linked_line" not in view
    assert view["source_label"] == "支付宝还款"
    assert view["amount_label"] == "¥200.00"
    assert view["targets"] == [
        {
            "public_id": "debt-1",
            "row_version": 7,
            "name": "花呗",
            "remaining_label": "¥500.00",
            "is_suggested": True,
            "is_selected": False,
        }
    ]


def test_view_pending_without_suggestion_has_no_provenance() -> None:
    view = _audit_row_view(_row(has_suggestion=False))
    assert view["status_label"] == "待确认"
    assert "provenance" not in view


def test_view_confirmed_shows_linked_and_not_suggestion() -> None:
    view = _audit_row_view(_row(status="confirmed", linked_debt_label="招商信用卡"))
    assert view["status_label"] == "已记账"
    assert view["status_tone"] == "ok"
    assert view["linked_line"] == "已记到「招商信用卡」"
    assert "provenance" not in view
    assert view["recede"] is False


def test_view_confirmed_null_label_falls_back_to_external_name() -> None:
    view = _audit_row_view(_row(status="confirmed", linked_debt_label=None))
    assert view["linked_line"] == "已记到「外部欠款」"


def test_view_dismissed_recedes_neutral() -> None:
    view = _audit_row_view(_row(status="dismissed"))
    assert view["status_label"] == "已忽略"
    assert view["status_tone"] == "muted"
    assert view["recede"] is True
