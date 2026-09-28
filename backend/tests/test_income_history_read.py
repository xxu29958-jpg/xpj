"""Readers see original estimates, not today's mutable plan or forecast."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, Expense, IncomePlanRevision, LedgerMember
from app.services import income_plan_service as income
from tests import test_web_income_edit_continuity
from tests.test_income_plan_revision_delivery import _seed_undated_single_month_plan

pytestmark = pytest.mark.real_db
web_income = test_web_income_edit_continuity.web_income
NOW = datetime(2026, 9, 5, tzinfo=UTC)
FIELDS = ("label", "source_type", "frequency", "income_month", "home_currency_code", "amount_cents", "pay_day", "status")


def _create():
    with SessionLocal() as db:
        plan = income.create_income_plan(db, tenant_id="owner", label="原工资预测", source_type="salary",
            home_currency_code="JPY", amount_cents=1200, pay_day=31, intent_month="2026-08", now=NOW)
        return plan.public_id


def _change(public_id, kind, **changes):
    with SessionLocal() as db:
        plan = income.get_income_plan(db, tenant_id="owner", public_id=public_id)
        command = {"edit": income.update_income_plan, "archive": income.archive_income_plan,
            "restore": income.restore_income_plan}[kind]
        return command(db, tenant_id="owner", public_id=public_id, expected_row_version=plan.row_version,
            intent_month="2026-09", now=NOW, **changes)


def _history(client, headers, public_id, **params):
    response = client.get(f"/api/income-plans/{public_id}/history", headers=headers, params=params)
    assert response.status_code == 200, response.text
    assert response.json()["ledger_id"] == "owner" and response.json()["public_id"] == public_id
    return response.json()


def _facts():
    with SessionLocal() as db:
        rows = [(r.revision_number, r.change_kind, r.recorded_at, tuple(getattr(r, key) for key in FIELDS))
            for r in db.scalars(select(IncomePlanRevision).order_by(IncomePlanRevision.revision_number.desc()))]
        counts = tuple(db.scalar(select(func.count()).select_from(model)) for model in (Expense, ApiIdempotencyKey))
        return rows, counts


def test_paging_after_later_edit_keeps_original_definitions_and_never_writes(client, identity):
    public_id = _create()
    _change(public_id, "edit", label="十一月奖金预测", frequency="one_time", income_month="2026-11",
        income_month_provided=True, source_type="bonus", amount_cents=1800)
    _change(public_id, "archive")
    _change(public_id, "restore")
    accepted, _ = _facts()
    first = _history(client, identity.app_headers, public_id, limit=2)
    _change(public_id, "edit", amount_cents=2200)
    before = _facts()
    second = _history(client, identity.app_headers, public_id, limit=2, before_version=first["next_before_version"])
    assert second["next_before_version"] is None
    items = first["items"] + second["items"]
    assert [item["row_version"] for item in items] == [4, 3, 2, 1]
    for item, row in zip(items, accepted, strict=True):
        assert item["change_kind"] == row[1]
        assert datetime.fromisoformat(item["recorded_at"].replace("Z", "+00:00")) == row[2]
        assert tuple(item["snapshot"][key] for key in FIELDS) == row[3]
    assert items[-1]["intent_month"] == items[-1]["effective_month"] == "2026-08"
    assert items[2]["intent_month"] == items[2]["effective_month"] == "2026-09"
    assert items[2]["snapshot"]["income_month"] == "2026-11"
    assert _history(client, identity.app_headers, public_id, limit=2, before_version=3) == second
    latest = _history(client, identity.app_headers, public_id)["items"]
    assert latest[0]["snapshot"]["amount_cents"] == 2200 and latest[-1]["snapshot"]["amount_cents"] == 1200
    assert client.get(f"/api/income-plans/{public_id}/history", headers=identity.app_headers,
        params={"before_version": 0}).status_code == 422
    assert _facts() == before


def test_archived_income_history_is_visible_to_reader_and_hidden_from_other_ledgers(web_income, identity):
    client, _ = web_income
    public_id = _create()
    _change(public_id, "archive")
    with SessionLocal.begin() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner"))
        member.role = "viewer"
    before = _facts()
    history = _history(client, identity.app_headers, public_id)
    assert [row["change_kind"] for row in history["items"]] == ["archive", "create"]
    page = client.get(f"/web/income-plans/{public_id}/history?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert "原工资预测" in page.text and "JPY 1200" in page.text and "不代表实际到账或账户余额" in page.text
    assert f"#income-{public_id}" in page.text and 'method="post"' not in page.text.split('<div class="plan-flow">')[1]
    assert client.get(f"/api/income-plans/{public_id}/history", headers=identity.gray_app_headers).status_code == 404
    with SessionLocal.begin() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner"))
        db.delete(member)
    refused = client.get(f"/api/income-plans/{public_id}/history", headers=identity.app_headers)
    assert refused.status_code in (401, 403) and "原工资预测" not in refused.text
    assert _facts() == before


def test_undated_baseline_keeps_unknown_months_without_inventing_earlier_income(client, identity):
    _, public_id, _ = _seed_undated_single_month_plan(NOW)
    before = _facts()
    row = _history(client, identity.app_headers, public_id)["items"][0]
    assert row["change_kind"] == "baseline" and row["intent_month"] is None and row["effective_month"] is None
    assert row["snapshot"]["income_month"] == "2026-08" and row["snapshot"]["amount_cents"] == 10000
    assert row["recorded_at"] == "2026-09-05T00:00:00Z"
    assert _facts() == before
