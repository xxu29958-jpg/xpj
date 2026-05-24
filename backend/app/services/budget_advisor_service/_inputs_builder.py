"""Assemble a fully-anonymised :class:`BudgetInputs` from live DB state.

This is the trust boundary between "what the backend knows" and "what
the AI advisor sees". Every real PII field (merchant canonical name,
ledger member account id) is swapped for a stable opaque placeholder
via the alias resolver (PR-2 tables) **before** the dataclass is built.
The outbound guard re-checks the shape one more time inside the
provider, but this builder is where the substitution actually happens.

Used by ``POST /api/budget/advise`` and any future server-side scheduled
budget reflection (e.g. month-end summary). Never used by surfaces that
should see raw data — call ``compute_personal_baseline`` /
``list_income_plans`` directly for that.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ledger_scope import add_ledger_scope, ledger_filter, ledger_scoped_select
from app.models import (
    Expense,
    Ledger,
    LedgerMember,
    MonthlyIncomePlan,
    RecurringItem,
)
from app.services.budget_advisor_service._aliases import (
    get_or_create_member_anon,
    get_or_create_merchant_anon,
)
from app.services.budget_advisor_service._models import (
    BudgetInputs,
    CategorySnapshot,
    FixedExpense,
    HistoricalBaseline,
    IncomePlan,
    MemberRef,
    MerchantSummary,
)
from app.services.budget_baseline_service import compute_personal_baseline
from app.services.category_service import normalize_category
from app.services.merchant_alias_service import (
    canonical_merchant_for,
    enabled_merchant_alias_map,
)
from app.services.merchant_service import display_merchant
from app.services.spending_contract_service import (
    month_bounds_utc,
    stat_time_expr,
)

# Default coarse class for recurring items. ``RecurringItem`` does not
# itself carry a category — they're discovered from expense rows, and a
# single merchant_key can have spread across categories over time. The
# advisor only needs the bucket class, not the exact category, so a
# stable label keeps the AI prompt simple.
_RECURRING_DEFAULT_CLASS = "订阅"
_MISSING_CATEGORY_CLASS = "其他"


def build_budget_inputs(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str = "Asia/Shanghai",
    home_currency: str = "CNY",
) -> BudgetInputs:
    """Build an anonymised :class:`BudgetInputs` for the given tenant + month.

    Side effect: writes alias rows the first time a merchant / member is
    seen this session — that's intentional and the documented behaviour
    of ``get_or_create_*`` (deterministic, idempotent).
    """

    start_utc, end_utc = month_bounds_utc(month, timezone_name)
    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    stat_time = stat_time_expr()

    members = _build_members(db, tenant_id=tenant_id)
    category_breakdown = _build_category_breakdown(
        db, tenant_id=tenant_id, start_utc=start_utc, end_utc=end_utc, stat_time=stat_time
    )
    merchant_summary = _build_merchant_summary(
        db,
        tenant_id=tenant_id,
        start_utc=start_utc,
        end_utc=end_utc,
        stat_time=stat_time,
        alias_map=alias_map,
    )
    income_plan = _build_income_plan(db, tenant_id=tenant_id)
    fixed_expenses = _build_fixed_expenses(
        db, tenant_id=tenant_id, alias_map=alias_map
    )
    historical_baseline = _build_historical_baseline(
        db, tenant_id=tenant_id
    )

    db.commit()  # persist alias rows allocated above
    return BudgetInputs(
        month=month,
        home_currency=home_currency,
        members=members,
        category_breakdown=category_breakdown,
        merchant_summary=merchant_summary,
        income_plan=income_plan,
        fixed_expenses=fixed_expenses,
        historical_baseline=historical_baseline,
    )


def _build_members(db: Session, *, tenant_id: str) -> list[MemberRef]:
    # LedgerMember uses ``ledger_id`` directly (not the tenant_id alias).
    rows = list(
        db.scalars(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == tenant_id)
            .where(LedgerMember.disabled_at.is_(None))
            .order_by(LedgerMember.id.asc())
        )
    )
    # Owner account too — single-member households still need member_1.
    owner_ids: set[int] = {row.account_id for row in rows}
    ledger = db.scalar(
        select(Ledger).where(Ledger.ledger_id == tenant_id).limit(1)
    )
    if ledger is not None and ledger.owner_account_id is not None:
        owner_ids.add(ledger.owner_account_id)

    members: list[MemberRef] = []
    for account_id in sorted(owner_ids):
        anon = get_or_create_member_anon(
            db, tenant_id=tenant_id, account_id=account_id
        )
        members.append(MemberRef(anon_id=anon))
    return members


def _build_category_breakdown(
    db: Session,
    *,
    tenant_id: str,
    start_utc,
    end_utc,
    stat_time,
) -> list[CategorySnapshot]:
    rows = db.execute(
        add_ledger_scope(
            select(
                Expense.category,
                func.coalesce(func.sum(Expense.amount_cents), 0),
                func.count(Expense.id),
            ).group_by(Expense.category),
            Expense,
            tenant_id,
        )
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(stat_time >= start_utc)
        .where(stat_time < end_utc)
    )
    snapshots: list[CategorySnapshot] = []
    for raw_category, amount, count in rows:
        snapshots.append(
            CategorySnapshot(
                category=normalize_category(raw_category) or _MISSING_CATEGORY_CLASS,
                amount_cents=int(amount or 0),
                count=int(count or 0),
            )
        )
    snapshots.sort(key=lambda row: -row.amount_cents)
    return snapshots


def _build_merchant_summary(
    db: Session,
    *,
    tenant_id: str,
    start_utc,
    end_utc,
    stat_time,
    alias_map: dict[str, str],
) -> list[MerchantSummary]:
    rows = db.execute(
        add_ledger_scope(
            select(
                func.coalesce(Expense.merchant, ""),
                Expense.category,
                func.coalesce(func.sum(Expense.amount_cents), 0),
                func.count(Expense.id),
            ).group_by(
                func.coalesce(Expense.merchant, ""), Expense.category
            ),
            Expense,
            tenant_id,
        )
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(stat_time >= start_utc)
        .where(stat_time < end_utc)
    )
    aggregated: dict[str, MerchantSummary] = {}
    for raw_merchant, raw_category, amount, count in rows:
        canonical = canonical_merchant_for(str(raw_merchant or ""), alias_map=alias_map)
        canonical = display_merchant(canonical) or _MISSING_CATEGORY_CLASS
        category_class = normalize_category(raw_category) or _MISSING_CATEGORY_CLASS
        anon = get_or_create_merchant_anon(
            db, tenant_id=tenant_id, merchant_canonical=canonical
        )
        key = f"{anon}:{category_class}"
        existing = aggregated.get(key)
        if existing is None:
            aggregated[key] = MerchantSummary(
                anon_id=anon,
                category_class=category_class,
                amount_cents=int(amount or 0),
                count=int(count or 0),
            )
        else:
            aggregated[key] = MerchantSummary(
                anon_id=anon,
                category_class=category_class,
                amount_cents=existing.amount_cents + int(amount or 0),
                count=existing.count + int(count or 0),
            )
    return sorted(aggregated.values(), key=lambda row: -row.amount_cents)


def _build_income_plan(db: Session, *, tenant_id: str) -> list[IncomePlan]:
    rows = list(
        db.scalars(
            ledger_scoped_select(MonthlyIncomePlan, tenant_id)
            .where(MonthlyIncomePlan.status == "active")
            .order_by(MonthlyIncomePlan.pay_day.asc(), MonthlyIncomePlan.id.asc())
        )
    )
    return [
        IncomePlan(
            source_type=row.source_type,
            amount_cents=int(row.amount_cents),
            pay_day=int(row.pay_day),
        )
        for row in rows
    ]


def _build_fixed_expenses(
    db: Session, *, tenant_id: str, alias_map: dict[str, str]
) -> list[FixedExpense]:
    rows = list(
        db.scalars(
            select(RecurringItem)
            .where(ledger_filter(RecurringItem, tenant_id))
            .where(RecurringItem.status == "active")
            .where(RecurringItem.frequency == "monthly")
            .order_by(RecurringItem.id.asc())
        )
    )
    fixed: list[FixedExpense] = []
    for row in rows:
        canonical = canonical_merchant_for(row.merchant_name, alias_map=alias_map)
        canonical = display_merchant(canonical) or row.merchant_name
        anon = get_or_create_merchant_anon(
            db, tenant_id=tenant_id, merchant_canonical=canonical
        )
        fixed.append(
            FixedExpense(
                anon_id=anon,
                category_class=_RECURRING_DEFAULT_CLASS,
                amount_cents=int(row.baseline_amount_cents),
                frequency=row.frequency,
            )
        )
    return fixed


def _build_historical_baseline(
    db: Session, *, tenant_id: str
) -> list[HistoricalBaseline]:
    personal = compute_personal_baseline(db, tenant_id=tenant_id)
    return [
        HistoricalBaseline(
            category=row.category,
            median_cents=int(row.median_cents),
            p75_cents=int(row.p75_cents),
        )
        for row in personal.categories
    ]
