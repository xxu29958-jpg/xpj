"""A1 Web timeline projection: honest collection history and page reachability."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.routes._web_expense_fact import (
    _timeline_changes,
    build_fact_timeline,
    timeline_page_url,
    web_fact_context,
)
from app.schemas import ExpenseRevisionListResponse, ExpenseRevisionResponse
from app.services.invitation_members import MemberSummary


def test_timeline_reads_requested_page_and_exposes_reachability() -> None:
    captured: dict[str, int] = {}

    def fake_list_expense_revisions(*_args, page: int, page_size: int, **_kwargs):
        captured.update(page=page, page_size=page_size)
        return ExpenseRevisionListResponse(
            items=[
                ExpenseRevisionResponse(
                    public_id="revision-1",
                    revision_number=1,
                    change_kind="confirmed",
                    reason="首次确认",
                    changed_fields=[],
                    before=None,
                    after={},
                    created_at=datetime(2026, 8, 1, tzinfo=UTC),
                )
            ],
            page=2,
            page_size=50,
            total=51,
        )

    with patch(
        "app.routes._web_expense_fact.list_expense_revisions",
        side_effect=fake_list_expense_revisions,
    ):
        timeline = build_fact_timeline(
            object(),
            tenant_id="owner",
            expense_id=7,
            home_currency_code="CNY",
            page=2,
            page_size=50,
            member_names={},
        )

    assert captured == {"page": 2, "page_size": 50}
    assert timeline["entries"][0]["reason"] == "首次确认"
    assert timeline["page"] == 2
    assert timeline["page_size"] == 50
    assert timeline["total"] == 51
    assert timeline["has_newer"] is True
    assert timeline["has_older"] is False


def test_collection_changes_expose_full_snapshots_without_inventing_row_identity() -> None:
    changes = _timeline_changes(
        {
            "change_kind": "correction",
            "changed_fields": ["items", "splits"],
            "before": {
                "amount_cents": 500,
                "items": [
                    {
                        "position": 0,
                        "name": "牛奶",
                        "quantity_text": "1 盒",
                        "unit_price_cents": 500,
                        "amount_cents": 500,
                        "category": "食品",
                    }
                ],
                "splits": [{"position": 0, "member_id": 7, "amount_cents": 500, "note": "早餐"}],
            },
            "after": {
                "amount_cents": 500,
                "items": [
                    {
                        "position": 0,
                        "name": "豆奶",
                        "quantity_text": "1 盒",
                        "unit_price_cents": 500,
                        "amount_cents": 500,
                        "category": "食品",
                    }
                ],
                "splits": [{"position": 0, "member_id": 9, "amount_cents": 500, "note": None}],
            },
        },
        "CNY",
        member_names={7: "小明"},
    )

    item_change = next(change for change in changes if change["label"] == "小票明细")
    assert item_change["details"] == {
        "before_rows": [
            {
                "title": "牛奶",
                "facts": ["1 盒", "单价 ¥5.00", "金额 ¥5.00", "食品"],
            }
        ],
        "after_rows": [
            {
                "title": "豆奶",
                "facts": ["1 盒", "单价 ¥5.00", "金额 ¥5.00", "食品"],
            }
        ],
    }
    split_change = next(change for change in changes if change["label"] == "家庭拆账")
    assert split_change["details"] == {
        "before_rows": [{"title": "小明", "facts": ["¥5.00", "早餐"]}],
        "after_rows": [{"title": "已移除的成员", "facts": ["¥5.00"]}],
    }
    assert "position" not in str(item_change["details"])
    assert "member_id" not in str(split_change["details"])


def test_timeline_page_url_keeps_the_fact_page_and_return_context() -> None:
    class RequestStub:
        query_params = {
            "ledger_id": "stale-ledger",
            "return_to": "/web/confirmed",
            "return_month": "2026-08",
            "msg": "do-not-carry-flash",
        }

    assert timeline_page_url(
        RequestStub(),
        expense_id=7,
        selected_ledger_id="owner",
        page=2,
    ) == (
        "/web/expenses/7/edit?ledger_id=owner&rev_page=2"
        "&return_to=%2Fweb%2Fconfirmed&return_month=2026-08#fact-timeline"
    )


def _disabled_member_revision_page() -> ExpenseRevisionListResponse:
    return ExpenseRevisionListResponse(
        items=[
            ExpenseRevisionResponse(
                public_id="revision-2",
                revision_number=2,
                change_kind="correction",
                reason="调整拆账",
                changed_fields=["splits"],
                before={
                    "amount_cents": 500,
                    "splits": [{"member_id": 7, "amount_cents": 200}],
                },
                after={
                    "amount_cents": 500,
                    "splits": [{"member_id": 7, "amount_cents": 300}],
                },
                created_at=datetime(2026, 8, 1, tzinfo=UTC),
            )
        ],
        page=1,
        page_size=50,
        total=1,
    )


def _disabled_member_summary() -> MemberSummary:
    return MemberSummary(
        member_id=7,
        account_id=70,
        account_public_id="account-7",
        account_name="小明",
        role="member",
        created_at="2026-01-01T00:00:00Z",
        disabled_at="2026-08-01T00:00:00Z",
        is_self=False,
    )


def test_web_fact_context_keeps_disabled_member_identity_in_revision_projection() -> None:
    class RequestStub:
        query_params: dict[str, str] = {}

    with (
        patch(
            "app.routes._web_expense_fact.web_edit_context",
            return_value={
                "expense": {},
                "can_write": True,
                "home_currency_code": "CNY",
            },
        ),
        patch(
            "app.routes._web_expense_fact.get_expense",
            return_value=SimpleNamespace(fact_revision=2, confirmed_at=None),
        ),
        patch(
            "app.routes._web_expense_fact.build_split_invite_context",
            return_value={},
        ),
        patch(
            "app.routes._web_expense_fact.list_active_split_members",
            return_value=[],
            create=True,
        ),
        patch(
            "app.services.invitation_members.list_members",
            return_value=[_disabled_member_summary()],
        ),
        patch(
            "app.routes._web_expense_fact.list_expense_revisions",
            return_value=_disabled_member_revision_page(),
        ),
    ):
        context = web_fact_context(
            object(),
            RequestStub(),
            [],
            "owner",
            7,
        )

    split_change = context["fact_timeline"][0]["changes"][0]
    assert split_change["details"] == {
        "before_rows": [{"title": "小明", "facts": ["¥2.00"]}],
        "after_rows": [{"title": "小明", "facts": ["¥3.00"]}],
    }
