"""Budget baseline DTOs (leaf).

Cold-start baseline lets v1.1 give "本月可自由支配" + per-category
suggestions before the user has accumulated months of personal data.
Two sources blend over time:

- ``DefaultBaseline``: framework-derived (50/30/20) + survey-anchored
  (BLS Consumer Expenditure Survey 2024 quintile averages) — used the
  moment a user finishes onboarding.
- Personal baseline (rolling P50/P75 from confirmed expenses) — folded
  in once the user has enough history. Lives in a separate sub-module.

This file defines the wire types only; algorithm and data files are in
sibling modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: Anchor for income bracketing. BLS uses quintiles ($35k / $60k / $95k /
#: $150k cutoffs from 2024). We bucket the same way for parity with the
#: published table, then ask the user which bracket they're in during
#: onboarding (more privacy-preserving than asking for an exact number).
IncomeQuintile = Literal["q1", "q2", "q3", "q4", "q5"]


@dataclass(frozen=True)
class CategoryBaseline:
    """Per-category monthly baseline in cents.

    ``median_cents`` mirrors the BLS / personal P50; ``p75_cents`` is the
    "comfortable upper bound" the advisor uses as a default budget target.
    Both are absolute amounts for the household, not percentages.
    """

    category: str
    median_cents: int
    p75_cents: int


@dataclass(frozen=True)
class DefaultBaseline:
    """A complete starting baseline for a household with no personal data.

    ``framework`` is the share-based partition ("needs/wants/savings");
    ``categories`` is the detailed per-category breakdown derived from
    the survey reference. Both must be consistent: the sum of category
    medians cannot exceed the framework's needs+wants share.
    """

    income_quintile: IncomeQuintile
    monthly_income_cents: int
    framework: FrameworkShares
    categories: tuple[CategoryBaseline, ...]


@dataclass(frozen=True)
class FrameworkShares:
    """Three-share partition (50/30/20 by default).

    Stored as integer permille (per-thousand) so we can express slightly
    off values like 503/297/200 without float drift, while keeping the
    sum equal to 1000 invariant.
    """

    needs_permille: int  # 500 = 50.0%
    wants_permille: int
    savings_permille: int

    def __post_init__(self) -> None:
        total = self.needs_permille + self.wants_permille + self.savings_permille
        if total != 1000:
            raise ValueError(
                f"FrameworkShares must sum to 1000 permille; got {total}"
            )
