"""v1.1 PR-6: monthly_income_plan model + CRUD + aggregate.

Lock down:

- Validation rules (label length, amount sign, pay_day range).
- Soft-delete (archive) + restore is idempotent.
- Aggregate ``total_monthly_income_cents`` only counts active rows.
- Tenant isolation on every operation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, Ledger
from app.services.income_plan_service import (
    archive_income_plan,
    create_income_plan,
    list_applicable_income_plans,
    list_income_plans,
    restore_income_plan,
    total_monthly_income_cents,
    update_income_plan,
)
from app.services.time_service import now_utc


def _make_extra_ledger(label: str) -> str:
    """Spin up a second ledger for tenant-isolation tests."""
    with SessionLocal() as db:
        now = now_utc()
        account = Account(display_name=f"income-test-{label}", created_at=now)
        db.add(account)
        db.flush()
        ledger = Ledger(
            ledger_id=f"income_{label}",
            name=f"income {label}",
            owner_account_id=account.id,
            created_at=now,
        )
        db.add(ledger)
        db.commit()
        return ledger.ledger_id


# ---------------------------------------------------------------------------
# create_income_plan validation
# ---------------------------------------------------------------------------


def test_create_income_plan_happy_path(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        plan = create_income_plan(
            db,
            tenant_id="owner",
            label="我的工资",
            source_type="salary",
            amount_cents=1_000_000,  # 10,000 元
            pay_day=10,
        )
    assert plan.label == "我的工资"
    assert plan.amount_cents == 1_000_000
    assert plan.pay_day == 10
    assert plan.status == "active"
    assert plan.public_id  # uuid assigned


def test_create_income_plan_strips_label_whitespace(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        plan = create_income_plan(
            db,
            tenant_id="owner",
            label="  我的副业  ",
            source_type="freelance",
            amount_cents=300_000,
            pay_day=20,
        )
    assert plan.label == "我的副业"


def test_create_income_plan_rejects_empty_label(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db, pytest.raises(AppError, match="收入名称"):
        create_income_plan(
            db,
            tenant_id="owner",
            label="   ",
            source_type="salary",
            amount_cents=100_000,
            pay_day=10,
        )


def test_create_income_plan_rejects_label_too_long(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db, pytest.raises(AppError, match="64"):
        create_income_plan(
            db,
            tenant_id="owner",
            label="x" * 65,
            source_type="salary",
            amount_cents=100_000,
            pay_day=10,
        )


def test_create_income_plan_rejects_negative_amount(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db, pytest.raises(AppError, match="负数"):
        create_income_plan(
            db,
            tenant_id="owner",
            label="负数测试",
            source_type="salary",
            amount_cents=-100,
            pay_day=10,
        )


@pytest.mark.parametrize("bad_day", [0, -1, 32, 100])
def test_create_income_plan_rejects_invalid_pay_day(identity, bad_day) -> None:  # noqa: ARG001
    with SessionLocal() as db, pytest.raises(AppError, match="发薪日"):
        create_income_plan(
            db,
            tenant_id="owner",
            label="无效日",
            source_type="salary",
            amount_cents=100_000,
            pay_day=bad_day,
        )


def test_create_income_plan_accepts_pay_day_edges(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        first = create_income_plan(
            db, tenant_id="owner", label="月初", source_type="salary",
            amount_cents=10_000, pay_day=1,
        )
        last = create_income_plan(
            db, tenant_id="owner", label="月末", source_type="bonus",
            amount_cents=20_000, pay_day=31,
        )
    assert first.pay_day == 1
    assert last.pay_day == 31


def test_create_one_time_income_requires_and_stores_income_month(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        plan = create_income_plan(
            db,
            tenant_id="owner",
            label="项目尾款",
            source_type="freelance",
            amount_cents=250_000,
            pay_day=28,
            frequency="one_time",
            income_month="2026-06",
        )
    assert plan.frequency == "one_time"
    assert plan.income_month == "2026-06"


def test_create_one_time_income_rejects_missing_income_month(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db, pytest.raises(AppError, match="到账月份"):
        create_income_plan(
            db,
            tenant_id="owner",
            label="项目尾款",
            source_type="freelance",
            amount_cents=250_000,
            pay_day=28,
            frequency="one_time",
            income_month=None,
        )


def test_monthly_income_ignores_income_month(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        plan = create_income_plan(
            db,
            tenant_id="owner",
            label="工资",
            source_type="salary",
            amount_cents=1_000_000,
            pay_day=10,
            frequency="monthly",
            income_month="2026-06",
        )
    assert plan.frequency == "monthly"
    assert plan.income_month is None


# ---------------------------------------------------------------------------
# update / archive / restore
# ---------------------------------------------------------------------------


def test_update_changes_only_provided_fields(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        plan = create_income_plan(
            db, tenant_id="owner", label="工资", source_type="salary",
            amount_cents=1_000_000, pay_day=10,
        )
        pid = plan.public_id
        token = plan.row_version
        updated = update_income_plan(
            db,
            tenant_id="owner",
            public_id=pid,
            expected_row_version=token,
            amount_cents=1_200_000,
        )
    assert updated.amount_cents == 1_200_000
    assert updated.label == "工资"  # unchanged
    assert updated.pay_day == 10  # unchanged


def test_update_rejects_archived_plan(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        plan = create_income_plan(
            db, tenant_id="owner", label="x", source_type="salary",
            amount_cents=100, pay_day=5,
        )
        token = plan.row_version
        archive_income_plan(
            db, tenant_id="owner", public_id=plan.public_id, expected_row_version=token
        )
        with pytest.raises(AppError, match="归档"):
            update_income_plan(
                db,
                tenant_id="owner",
                public_id=plan.public_id,
                expected_row_version=token,
                label="y",
            )


def test_update_unknown_public_id_returns_not_found(identity) -> None:  # noqa: ARG001
    from datetime import UTC, datetime
    with SessionLocal() as db, pytest.raises(AppError, match="不存在"):
        update_income_plan(
            db,
            tenant_id="owner",
            public_id="nonexistent",
            expected_row_version=datetime(2026, 5, 4, tzinfo=UTC),
            label="x",
        )


def test_archive_is_idempotent(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        plan = create_income_plan(
            db, tenant_id="owner", label="a", source_type="salary",
            amount_cents=100, pay_day=1,
        )
        first = archive_income_plan(
            db, tenant_id="owner", public_id=plan.public_id,
            expected_row_version=plan.row_version,
        )
        second = archive_income_plan(
            db, tenant_id="owner", public_id=plan.public_id,
            expected_row_version=plan.row_version,
        )
    assert first.status == "archived"
    assert second.status == "archived"
    assert first.archived_at == second.archived_at  # second call doesn't touch timestamp


def test_restore_reactivates_archived_plan(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        plan = create_income_plan(
            db, tenant_id="owner", label="b", source_type="salary",
            amount_cents=100, pay_day=1,
        )
        archived = archive_income_plan(
            db, tenant_id="owner", public_id=plan.public_id,
            expected_row_version=plan.row_version,
        )
        restored = restore_income_plan(
            db, tenant_id="owner", public_id=plan.public_id,
            expected_row_version=archived.row_version,
        )
    assert restored.status == "active"
    assert restored.archived_at is None


# ---------------------------------------------------------------------------
# list / total
# ---------------------------------------------------------------------------


def test_list_active_excludes_archived(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        active = create_income_plan(
            db, tenant_id="owner", label="alive", source_type="salary",
            amount_cents=100, pay_day=10,
        )
        archived = create_income_plan(
            db, tenant_id="owner", label="dead", source_type="bonus",
            amount_cents=200, pay_day=20,
        )
        archive_income_plan(
            db, tenant_id="owner", public_id=archived.public_id,
            expected_row_version=archived.row_version,
        )
        listed = list_income_plans(db, tenant_id="owner")
    pids = {p.public_id for p in listed}
    assert active.public_id in pids
    assert archived.public_id not in pids


def test_list_with_status_none_returns_everything(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        active = create_income_plan(
            db, tenant_id="owner", label="alive", source_type="salary",
            amount_cents=100, pay_day=10,
        )
        archived = create_income_plan(
            db, tenant_id="owner", label="dead", source_type="bonus",
            amount_cents=200, pay_day=20,
        )
        archive_income_plan(
            db, tenant_id="owner", public_id=archived.public_id,
            expected_row_version=archived.row_version,
        )
        listed = list_income_plans(db, tenant_id="owner", status=None)
    pids = {p.public_id for p in listed}
    assert active.public_id in pids
    assert archived.public_id in pids


def test_total_monthly_income_only_counts_active(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        create_income_plan(
            db, tenant_id="owner", label="alive", source_type="salary",
            amount_cents=1_000_000, pay_day=10,
        )
        create_income_plan(
            db, tenant_id="owner", label="alive2", source_type="bonus",
            amount_cents=500_000, pay_day=15,
        )
        dead = create_income_plan(
            db, tenant_id="owner", label="dead", source_type="salary",
            amount_cents=999_999, pay_day=20,
        )
        archive_income_plan(
            db, tenant_id="owner", public_id=dead.public_id,
            expected_row_version=dead.row_version,
        )
        total = total_monthly_income_cents(db, tenant_id="owner")
    assert total == 1_500_000


def test_total_monthly_income_counts_one_time_only_for_matching_month(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        create_income_plan(
            db,
            tenant_id="owner",
            label="salary",
            source_type="salary",
            amount_cents=1_000_000,
            pay_day=10,
        )
        create_income_plan(
            db,
            tenant_id="owner",
            label="one-off June",
            source_type="bonus",
            amount_cents=200_000,
            pay_day=20,
            frequency="one_time",
            income_month="2026-06",
        )
        create_income_plan(
            db,
            tenant_id="owner",
            label="one-off July",
            source_type="bonus",
            amount_cents=300_000,
            pay_day=20,
            frequency="one_time",
            income_month="2026-07",
        )
        june_total = total_monthly_income_cents(
            db, tenant_id="owner", month="2026-06", as_of=datetime(2026, 6, 30, tzinfo=UTC)
        )
        july_total = total_monthly_income_cents(
            db, tenant_id="owner", month="2026-07", as_of=datetime(2026, 7, 31, tzinfo=UTC)
        )
        recurring_only = total_monthly_income_cents(db, tenant_id="owner")
        june_rows = list_applicable_income_plans(
            db, tenant_id="owner", month="2026-06", as_of=datetime(2026, 6, 30, tzinfo=UTC)
        )
    assert june_total == 1_200_000
    assert july_total == 1_300_000
    assert recurring_only == 1_000_000
    assert {row.label for row in june_rows} == {"salary", "one-off June"}


def test_current_month_income_waits_until_pay_day(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        create_income_plan(
            db,
            tenant_id="owner",
            label="late salary",
            source_type="salary",
            amount_cents=1_000_000,
            pay_day=30,
            frequency="one_time",
            income_month="2026-06",
        )
        before_payday = total_monthly_income_cents(
            db, tenant_id="owner", month="2026-06", as_of=datetime(2026, 6, 29, tzinfo=UTC)
        )
        on_payday = total_monthly_income_cents(
            db, tenant_id="owner", month="2026-06", as_of=datetime(2026, 6, 30, tzinfo=UTC)
        )

    assert before_payday == 0
    assert on_payday == 1_000_000


def test_total_returns_zero_when_no_plans(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        total = total_monthly_income_cents(db, tenant_id="owner")
    assert total == 0


def test_tenant_isolation_on_list_and_total(identity) -> None:  # noqa: ARG001
    other = _make_extra_ledger("iso")
    with SessionLocal() as db:
        create_income_plan(
            db, tenant_id="owner", label="own", source_type="salary",
            amount_cents=100_000, pay_day=10,
        )
        create_income_plan(
            db, tenant_id=other, label="theirs", source_type="salary",
            amount_cents=999_000, pay_day=15,
        )
        own_listed = list_income_plans(db, tenant_id="owner")
        other_listed = list_income_plans(db, tenant_id=other)
        own_total = total_monthly_income_cents(db, tenant_id="owner")
        other_total = total_monthly_income_cents(db, tenant_id=other)
    assert len(own_listed) == 1
    assert own_listed[0].label == "own"
    assert len(other_listed) == 1
    assert other_listed[0].label == "theirs"
    assert own_total == 100_000
    assert other_total == 999_000
