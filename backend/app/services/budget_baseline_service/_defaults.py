"""Cold-start baseline: 50/30/20 framework + BLS 2024 quintile reference.

Sources (public domain / official):

- 50/30/20 rule: needs 50% / wants 30% / savings 20% — widely-used
  framework popularised by Elizabeth Warren in *All Your Worth*; the
  default partition every budgeting tool (Monarch, YNAB, Copilot, etc)
  exposes when a user has no history.
- BLS Consumer Expenditure Survey 2024 (released Dec 2025) — used for
  category share anchors. Top categories with reported percentages of
  total household spending: housing 33.4%, transportation 17.0%,
  food 12.9%, personal insurance / pensions 12.5%, healthcare 7.9%,
  entertainment ~5.0%. Per-quintile dollar values are summarised by
  income bracket (q1: lowest 20% — q5: highest 20%).

NOT a substitute for personal data once the user has accumulated some.
Personal P50/P75 takes over via :mod:`_blend` (next PR).

US BLS shares are an approximation for non-US users; ``v1.1`` ships
the US table only and will swap in localised data behind the same
``get_default_baseline`` API once a CN Household Survey table is added.
"""

from __future__ import annotations

from app.services.budget_baseline_service._models import (
    CategoryBaseline,
    DefaultBaseline,
    FrameworkShares,
    IncomeQuintile,
)

#: 50/30/20 default partition. Callers can pass a custom override.
FRAMEWORK_50_30_20 = FrameworkShares(
    needs_permille=500,
    wants_permille=300,
    savings_permille=200,
)

#: Average monthly household income (cents) per BLS 2024 quintile,
#: rough mid-point of each bracket. Cents to stay integer-clean.
_QUINTILE_MONTHLY_INCOME_CENTS: dict[IncomeQuintile, int] = {
    "q1": 290_000_00,    # ~$2,900/mo  (lowest 20%)
    "q2": 530_000_00,    # ~$5,300/mo
    "q3": 740_000_00,    # ~$7,400/mo
    "q4": 1_080_000_00,  # ~$10,800/mo
    "q5": 1_950_000_00,  # ~$19,500/mo (highest 20%)
}

#: Per-category share of total household spending from BLS 2024 (permille).
#: Map a category label that aligns with the project's category catalog
#: (餐饮 / 住房 / etc, see app/services/category_service.py); fall back
#: to "其他" for whatever the survey didn't classify.
#:
#: Note: BLS uses English categories (Housing / Transportation / etc).
#: We translate to the project's Chinese labels using the canonical
#: category catalog. "保险与养老金" + "教育" + "礼物与捐赠" + "杂项"
#: fold into "其他" since the project doesn't break them out.
_BLS_CATEGORY_SHARE_PERMILLE: dict[str, int] = {
    "住房": 334,         # housing 33.4%
    "交通": 170,         # transportation 17.0%
    "餐饮": 129,         # food (groceries + dining) 12.9%
    "医疗": 79,          # healthcare 7.9%
    "娱乐": 50,          # entertainment ~5.0%
    "购物": 30,          # apparel + services ~3.0%
    "通讯": 25,          # telephone + internet ~2.5%
    "其他": 183,         # insurance + pensions + education + misc residual
}


def get_default_baseline(
    *,
    income_quintile: IncomeQuintile,
    monthly_income_cents: int | None = None,
    framework: FrameworkShares = FRAMEWORK_50_30_20,
) -> DefaultBaseline:
    """Return a starter baseline keyed off the user's income bracket.

    ``monthly_income_cents`` overrides the quintile mid-point when the
    user gave a precise number in onboarding. Category amounts then scale
    linearly from the BLS share table so totals stay within
    ``needs + wants`` (no SAvings overspend).
    """

    income_cents = monthly_income_cents or _QUINTILE_MONTHLY_INCOME_CENTS[income_quintile]
    # Total spendable (needs + wants); savings is the residual.
    spendable_permille = framework.needs_permille + framework.wants_permille
    spendable_cents = income_cents * spendable_permille // 1000

    # Convert BLS shares (relative to total spending) into per-category
    # cents budgets, scaling so the sum matches ``spendable_cents``.
    bls_total_permille = sum(_BLS_CATEGORY_SHARE_PERMILLE.values())
    categories: list[CategoryBaseline] = []
    for category, share_permille in _BLS_CATEGORY_SHARE_PERMILLE.items():
        median = spendable_cents * share_permille // bls_total_permille
        # P75 estimated as 1.3x median (BLS quintile dispersion ratio is
        # roughly 1.3x between Q3 and Q4 spending within a category —
        # rough but a deterministic starting point until personal P75
        # data takes over).
        p75 = int(median * 1.3)
        categories.append(
            CategoryBaseline(
                category=category,
                median_cents=median,
                p75_cents=p75,
            )
        )
    return DefaultBaseline(
        income_quintile=income_quintile,
        monthly_income_cents=income_cents,
        framework=framework,
        categories=tuple(categories),
    )


def discretionary_cents(baseline: DefaultBaseline) -> int:
    """Return the monthly discretionary cap implied by a default baseline.

    ``discretionary = income * wants_permille / 1000``. This is the "wants"
    bucket — what the user can spend without dipping into needs or
    savings. The v1.1 "本月可自由支配" formula starts from this value and
    subtracts any committed fixed monthly outflows.
    """
    return baseline.monthly_income_cents * baseline.framework.wants_permille // 1000


def quintile_for_monthly_income(income_cents: int) -> IncomeQuintile:
    """Snap a precise monthly income to its BLS quintile bracket.

    Cut-offs derived from BLS 2024 quintile boundaries (annual: $35k /
    $60k / $95k / $150k → monthly equivalents). Defensive for negatives
    (snaps to q1).
    """
    monthly = max(0, income_cents)
    if monthly < 35_000_00 / 12 * 100:   # < ~$2,917/mo
        return "q1"
    if monthly < 60_000_00 / 12 * 100:   # < ~$5,000/mo
        return "q2"
    if monthly < 95_000_00 / 12 * 100:   # < ~$7,917/mo
        return "q3"
    if monthly < 150_000_00 / 12 * 100:  # < ~$12,500/mo
        return "q4"
    return "q5"
