"""v1.1 baseline service — cold-start default baseline for new users.

Lets the budget pipeline produce useful "本月可自由支配" + per-category
suggestions on day zero, before any personal expense history exists.
Sources are the 50/30/20 framework + BLS Consumer Expenditure Survey
2024 anchor data (US public-domain official statistics).

This PR ships the **default** baseline only. Personal P50/P75 derived
from rolling user history + the blend algorithm that fades between them
ship in a follow-up PR.

External API is intentionally narrow:

- :func:`get_default_baseline` — turn an income bracket into a full
  ``DefaultBaseline``.
- :func:`discretionary_cents` — the "wants" cap derived from a default
  baseline; the seed value for "本月可自由支配".
- :func:`quintile_for_monthly_income` — snap a precise income to the
  closest BLS quintile bucket.
"""

from __future__ import annotations

from app.services.budget_baseline_service._blend import (
    blend_baselines,
    personal_trust_weight,
)
from app.services.budget_baseline_service._defaults import (
    FRAMEWORK_50_30_20,
    discretionary_cents,
    get_default_baseline,
    quintile_for_monthly_income,
)
from app.services.budget_baseline_service._discretionary import (
    DiscretionaryBreakdown,
    compute_monthly_discretionary,
)
from app.services.budget_baseline_service._fixed_expense_reader import (
    total_active_recurring_monthly_cents,
)
from app.services.budget_baseline_service._models import (
    CategoryBaseline,
    DefaultBaseline,
    FrameworkShares,
    IncomeQuintile,
)
from app.services.budget_baseline_service._personal import (
    PersonalBaseline,
    compute_personal_baseline,
)
from app.services.budget_baseline_service._spent_reader import (
    total_confirmed_spent_cents,
)

__all__ = [
    "FRAMEWORK_50_30_20",
    "CategoryBaseline",
    "DefaultBaseline",
    "DiscretionaryBreakdown",
    "FrameworkShares",
    "IncomeQuintile",
    "PersonalBaseline",
    "blend_baselines",
    "compute_monthly_discretionary",
    "compute_personal_baseline",
    "discretionary_cents",
    "get_default_baseline",
    "personal_trust_weight",
    "quintile_for_monthly_income",
    "total_active_recurring_monthly_cents",
    "total_confirmed_spent_cents",
]
