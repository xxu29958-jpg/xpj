"""Reports types and bucket dataclass (leaf)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ReportGranularity = Literal["day", "week", "month"]
ReportRankingMetric = Literal["amount", "count"]


@dataclass(frozen=True)
class _TrendBucket:
    bucket: str
    label: str
    start_utc: datetime
    end_utc: datetime
