"""Blend a cold-start default baseline with the user's rolling personal
baseline. Personal data wins once enough months are observed; before
that the default carries weight.

Shrinkage weight (linear, capped at 6 months):

    personal_weight = min(months_observed, 6) / 6
    blended = personal * personal_weight + default * (1 - personal_weight)

Six months is the conventional cut-off — long enough to capture
quarterly bills and seasonal variation, short enough that "stale"
historical data doesn't drag the suggestion away from recent reality.
"""

from __future__ import annotations

from app.services.budget_baseline_service._models import (
    CategoryBaseline,
    DefaultBaseline,
)
from app.services.budget_baseline_service._personal import PersonalBaseline

_FULL_TRUST_MONTHS = 6


def blend_baselines(
    *,
    default: DefaultBaseline,
    personal: PersonalBaseline,
) -> tuple[CategoryBaseline, ...]:
    """Return a per-category baseline that fades from default to personal
    as the user accumulates months of confirmed history."""

    personal_weight = min(personal.months_observed, _FULL_TRUST_MONTHS) / _FULL_TRUST_MONTHS
    default_by_category = {row.category: row for row in default.categories}
    personal_by_category = {row.category: row for row in personal.categories}

    categories: list[CategoryBaseline] = []
    seen: set[str] = set()
    for category, default_row in default_by_category.items():
        seen.add(category)
        personal_row = personal_by_category.get(category)
        if personal_row is None:
            # No personal data for this category yet — keep the default
            # as-is. Don't fabricate a "blended" value out of thin air.
            categories.append(default_row)
            continue
        median = int(
            personal_row.median_cents * personal_weight
            + default_row.median_cents * (1 - personal_weight)
        )
        p75 = int(
            personal_row.p75_cents * personal_weight
            + default_row.p75_cents * (1 - personal_weight)
        )
        categories.append(
            CategoryBaseline(
                category=category,
                median_cents=median,
                p75_cents=max(p75, median),
            )
        )

    # Categories the user spends on that are not in the default table
    # (e.g. a niche category the BLS table folded into 其他). Carry them
    # over at full personal weight — they're not "blends" because there
    # is no default counterpart to blend with.
    for category, personal_row in personal_by_category.items():
        if category not in seen:
            categories.append(personal_row)

    categories.sort(key=lambda row: -row.median_cents)
    return tuple(categories)


def personal_trust_weight(months_observed: int) -> float:
    """Inspectable view of the shrinkage weight — useful in the UI to
    explain "we're using mostly default / mostly your data"."""
    return min(max(months_observed, 0), _FULL_TRUST_MONTHS) / _FULL_TRUST_MONTHS
