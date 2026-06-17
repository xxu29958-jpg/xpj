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
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Debt
from app.services.debt_service import (
    compute_remaining,
    compute_remaining_as_of,
    latest_fact_at,
)
from app.services.time_service import ensure_utc, safe_zone

# At most a 90-day lookback; never longer than the plan's own age (a fresh plan is judged
# on its real history). Sub-fortnight windows make the rate statistically noisy and a
# days-old plan would project a wild date — suppress rather than fake (§7.0 R4). The
# numbers are tunable; the redline is "suppress on thin/zero/mixed data".
_PROJECTION_WINDOW_DAYS = 90
_PROJECTION_MIN_TRACKING_DAYS = 14

# Suppress-on-stale floor (8e-6d / 杠杆④): a positive-velocity projection drawn only from a
# repayment recorded weeks ago is a confident date the data no longer backs — the
# projection-lying-on-stale-data failure mode (the actual debt-domain bottleneck under a
# hand-entry model: the user stops updating and the pace silently goes stale). If the most
# recent fold-changing fact across the linked Debts is older than this, suppress the date and
# surface how long the data has gone quiet instead. 35 days ≈ one credit-card billing cycle
# plus a few days' grace. This is the single "has-a-rhythm" default — applied uniformly to
# revolving cards AND not-yet-classified (unspecified) external debt: the unspecified bucket is
# dominated by keyword-missed monthly debts (labelled "招行", a card's last-4, "还款"…), which
# deserve the SAME freshness bar as a known card, not a looser one. (8e-6e adds a manual
# `one_off`/no-rhythm kind that suppresses the projection entirely — it does NOT move this
# number.) "Conservative" here means nudge-to-update slightly EARLY, not avoid-disturbing: a
# late nudge leaves the user acting on stale data, which costs more than one extra reminder.
# Tunable to the household's cadence; the redline is "never print a date the most recent data
# no longer supports" (§7.0 R4).
_PROJECTION_STALE_DAYS = 35


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


def _days_since_last_activity(db: Session, debts: list[Debt], *, now: datetime) -> int | None:
    """Whole days since the most recent fold-changing FACT across ``debts``, or ``None`` if no
    linked Debt has any fact yet.

    Staleness is measured off paydown activity ONLY — the append-only facts
    (:func:`latest_fact_at`) — NOT a Debt's principal-establishing ``created_at``. Linking a
    brand-new Debt raises remaining (it freezes a new principal); it is not paydown and must not
    reset the staleness clock, otherwise adding a fresh Debt to a plan would silently revive a
    projection drawn from weeks-old data. The floor only runs once a positive-velocity
    projection exists (``reduction > 0``), which guarantees ≥1 fact across the set, so this
    returns ``None`` only on a path no live projection reaches — the caller still guards for it.
    """
    fact_instants = [
        latest for debt in debts if (latest := latest_fact_at(db, debt)) is not None
    ]
    if not fact_instants:
        return None
    return (now - max(fact_instants)).days


def compute_external_kpi(
    db: Session, debts: list[Debt], *, now: datetime
) -> tuple[int | None, date | None, int | None]:
    """Payoff projection for a PURE-EXTERNAL plan's non-voided linked Debts.

    Returns ``(tracking_days, projected_payoff_date, days_since_last_activity)`` as one of three
    mutually-exclusive shapes:

    * **fresh** — ``(tracking_days, projected_payoff_date, None)``: a paydown pace observed over
      recent data; show the projected month.
    * **stale** — ``(None, None, days_since_last_activity)``: a paydown pace WOULD project, but
      the most recent fact is older than ``_PROJECTION_STALE_DAYS`` (8e-6d / 杠杆④) — suppress the
      date and carry how many days the data has gone quiet so the UI can say "已 N 天没更新"
      instead of a date the stale data no longer supports.
    * **none** — ``(None, None, None)``: thin / no observed paydown / mixed currency / empty.
      This also covers a Debt whose only paydown predates the 90-day window: there is no
      in-window pace to call "stale", so it honestly reads as "not enough recent data" rather
      than a fabricated date — the §7.0 R4 redline ("never print a date the data no longer
      supports") holds in either case, only the copy differs.

    See the module docstring for the velocity / created_at / suppression contract.
    """
    if not debts:
        return None, None, None
    # Cross-currency guard: a remaining sum across different home currencies is meaningless,
    # so the projection (which divides into that sum) would be nonsense. Defensive parity
    # with the Android ``sharedHomeCurrencyCode`` guard over the SAME non-voided set the
    # projection consumes — today ``home_currency_code`` is a single global value (every
    # Debt freezes the one home currency), so this never trips in practice; it is here for
    # a future multi-home-currency world and to keep the server the authority (§4), not the
    # client. (The evaluator never summed amounts across links before — this is new code.)
    if len({debt.home_currency_code for debt in debts}) != 1:
        return None, None, None
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
        return None, None, None
    # Suppress-on-stale floor (8e-6d / 杠杆④): the pace above is real but may be drawn from a
    # repayment recorded weeks ago. If nothing has been recorded recently, do not print a
    # confident date the stale data no longer supports — surface the silence instead (§7.0 R4).
    stale_days = _days_since_last_activity(db, debts, now=now)
    if stale_days is not None and stale_days > _PROJECTION_STALE_DAYS:
        return None, None, stale_days
    today = now.astimezone(safe_zone(get_settings().ocr_default_timezone)).date()
    return tracking_days, today + timedelta(days=days_left), None


class ExternalPayoffKpi(NamedTuple):
    """The pure-external payoff KPI bundle attached to a debt_repayment evaluation.

    Every field is ``None`` for a non-pure-external plan (the §4 server gate). See
    :func:`external_payoff_kpi`. ``three_state`` needs both a projection and a deadline;
    ``days_since_last_activity`` is set only when the projection was suppressed for staleness.
    """

    tracking_days: int | None
    projected_payoff_date: date | None
    target_date: date | None
    three_state: str | None
    days_since_last_activity: int | None


_EMPTY_PAYOFF_KPI = ExternalPayoffKpi(None, None, None, None, None)


def external_payoff_kpi(
    db: Session, non_voided_debts: list[Debt], *, now: datetime, target_date: date | None
) -> ExternalPayoffKpi:
    """ADR-0049 §7.0 / 8e-6b+6c+6d server gate (§4): the payoff KPI for a PURE-EXTERNAL plan.

    The projection + deadline echo + three-state + staleness signal are assembled ONLY when
    every non-voided linked Debt is external (``!= 'member'`` byte-matches the Android
    composition's external bucket). Member / mixed / all-voided plans get the all-None bundle,
    so /web, /owner, exports, and tests never see a §7.0-forbidden payoff dashboard on a
    Communal plan. Read-only — identical on viewer / writer.
    """
    is_pure_external = bool(non_voided_debts) and all(
        debt.counterparty_type != "member" for debt in non_voided_debts
    )
    if not is_pure_external:
        return _EMPTY_PAYOFF_KPI
    tracking_days, projected, days_since = compute_external_kpi(db, non_voided_debts, now=now)
    return ExternalPayoffKpi(
        tracking_days=tracking_days,
        projected_payoff_date=projected,
        target_date=target_date,
        three_state=payoff_three_state(projected, target_date),
        days_since_last_activity=days_since,
    )
