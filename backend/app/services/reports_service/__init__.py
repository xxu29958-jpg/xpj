"""Reports service: monthly overview + 6-month summary + CSV export.

Split into 5 private sub-modules by responsibility:

- ``_models``: types + ``_TrendBucket`` dataclass.
- ``_time``: timezone / month / day helpers (thin wrappers over
  spending_contract_service).
- ``_aggregation``: range amount/count + trend buckets + bucket amount counts.
- ``_ranking``: merchant ranking + category totals / comparison.
- ``_api``: public ``reports_overview`` / ``six_month_summary`` /
  ``export_reports_overview_csv``.

External callers keep importing from ``app.services.reports_service``.
"""

from __future__ import annotations

from app.services.reports_service._api import (
    export_reports_overview_csv,
    reports_overview,
    six_month_summary,
)
from app.services.reports_service._models import (
    ReportGranularity,
    ReportRankingMetric,
)

__all__ = [
    "ReportGranularity",
    "ReportRankingMetric",
    "export_reports_overview_csv",
    "reports_overview",
    "six_month_summary",
]
