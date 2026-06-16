"""ADR-0049 §7.0 / 8e-6b: the external-debt payoff projection (velocity → payoff date).

Reserved EXCLUSIVELY for pure-external debt_repayment plans (§7.0: member debt is
Communal, never a payoff dashboard — the caller gates on every non-voided linked Debt
being external). The projection is honest by construction:

* **Velocity is the ACTUAL reduction in total remaining over the window**
  (``remaining_as_of(window_start) − remaining_now``), not a raw repayment sum — so a
  Debt knocked down by a negative ``DebtAdjustment`` (a write-off, with no repayment row)
  shows real downward velocity instead of looking stalled / "at risk" (R4 / CRITIQUE-1).
* **The window is measured on fact ``created_at``** (the recording cadence, indexed), NOT
  the user-editable ``paid_at`` — a back-dated entry cannot deflate the observed pace.
* **Honest fallback (R4): suppress (→ None) rather than fabricate** on mixed currency,
  thin data, no observed reduction, or a zero balance. Never ∞, never "today", never a
  fake-green.
* **"today" is the accounting-tz calendar day** (mirroring ``current_month``), so the
  projection does not drift a day across the Asia/Shanghai midnight.

Split out of ``goal_debt_repayment_service`` so the evaluator stays focused and this
correctness-sensitive math is an isolated, directly-testable unit.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Debt
from app.services.debt_service import compute_remaining, compute_remaining_as_of
from app.services.time_service import ensure_utc, safe_zone

# At most a 90-day lookback; never longer than the plan's own age (a fresh plan is judged
# on its real history). Sub-fortnight windows make the rate statistically noisy and a
# days-old plan would project a wild date — suppress rather than fake (§7.0 R4). The
# numbers are tunable; the redline is "suppress on thin/zero/mixed data".
_PROJECTION_WINDOW_DAYS = 90
_PROJECTION_MIN_TRACKING_DAYS = 14


def project_payoff_days(remaining_now: int, reduction: int, tracking_days: int) -> int | None:
    """Days until payoff at the observed pace, or ``None`` to suppress (pure math).

    ``reduction`` is the drop in TOTAL remaining over ``tracking_days`` (forgiveness and
    signed adjustments included, so a debt resolved by waiver/write-off counts as real
    progress). Honest fallback (ADR-0049 §7.0 R4 — never print a fabricated date): suppress
    when nothing remains, no net paydown was observed, or the window is too thin.
    """
    if (
        remaining_now <= 0
        or reduction <= 0
        or tracking_days < _PROJECTION_MIN_TRACKING_DAYS
    ):
        return None
    daily_velocity = reduction / tracking_days
    return math.ceil(remaining_now / daily_velocity)


def payoff_three_state(projected_payoff_date: date | None, target_date: date | None) -> str | None:
    """ADR-0049 §7.0 / 8e-6c: On track / Ahead / At risk, by the projected-payoff MONTH vs the
    deadline MONTH (pure function).

    Month-granularity matches the month-granular projection display and avoids day-level
    flapping (a few days late is still ``on_track``). Returns ``None`` unless BOTH a projection
    and a deadline exist — never editorialise on missing data (§7.0 R4 / de-shame). ``at_risk``
    is a FACTUAL "later than planned" state, NOT a shame trigger (the UI renders it amber/warn,
    never red, with no "pay faster" nudge).
    """
    if projected_payoff_date is None or target_date is None:
        return None
    projected_month = (projected_payoff_date.year, projected_payoff_date.month)
    target_month = (target_date.year, target_date.month)
    if projected_month < target_month:
        return "ahead"
    if projected_month > target_month:
        return "at_risk"
    return "on_track"


def compute_external_kpi(
    db: Session, debts: list[Debt], *, now: datetime
) -> tuple[int | None, date | None]:
    """Payoff projection for a PURE-EXTERNAL plan's non-voided linked Debts.

    Returns ``(tracking_days, projected_payoff_date)`` — both populated together or both
    ``None``. See the module docstring for the velocity / created_at / suppression contract.
    """
    if not debts:
        return None, None
    # Cross-currency guard: a remaining sum across different home currencies is meaningless,
    # so the projection (which divides into that sum) would be nonsense. Defensive parity
    # with the Android ``sharedHomeCurrencyCode`` guard over the SAME non-voided set the
    # projection consumes — today ``home_currency_code`` is a single global value (every
    # Debt freezes the one home currency), so this never trips in practice; it is here for
    # a future multi-home-currency world and to keep the server the authority (§4), not the
    # client. (The evaluator never summed amounts across links before — this is new code.)
    if len({debt.home_currency_code for debt in debts}) != 1:
        return None, None
    window_start = now - timedelta(days=_PROJECTION_WINDOW_DAYS)
    earliest_created = min(ensure_utc(debt.created_at) for debt in debts)
    observation_start = max(window_start, earliest_created)
    tracking_days = (now - observation_start).days
    remaining_now = sum(compute_remaining(db, debt) for debt in debts)
    remaining_then = sum(
        compute_remaining_as_of(db, debt, observation_start) for debt in debts
    )
    days_left = project_payoff_days(remaining_now, remaining_then - remaining_now, tracking_days)
    if days_left is None:
        return None, None
    today = now.astimezone(safe_zone(get_settings().ocr_default_timezone)).date()
    return tracking_days, today + timedelta(days=days_left)
