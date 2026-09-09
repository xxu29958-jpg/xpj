"""Cold-start defaults, blending and discretionary arithmetic.

Personal spending history is read by learning_service._budget_quantile.
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
from app.services.budget_baseline_service._models import (
    CategoryBaseline,
    DefaultBaseline,
    FrameworkShares,
    IncomeQuintile,
    PersonalBaseline,
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
    "discretionary_cents",
    "get_default_baseline",
    "personal_trust_weight",
    "quintile_for_monthly_income",
]
