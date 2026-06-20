"""ADR-0049 §B 完整 installment: the deterministic payoff date of an installment debt.

An ``installment`` external debt's payoff is CONTRACTUAL, not a velocity guess: the schedule is
``installment_count`` periods of ``installment_period_months`` months, so the whole obligation is
cleared at ``建账日 + count×period months`` regardless of interest, fee, or amortization shape
(equal-principal vs equal-installment only change the per-period AMOUNT, never the期数/日期 — §A).
This single source feeds both the per-Debt ``DebtResponse.installment_payoff_date`` and the
goal-level ``external_payoff_kpi`` (an all-installment plan shows ``max`` of its debts' dates
instead of the suppressed velocity projection).

The creation instant is read in the accounting timezone (mirroring the KPI's "today is the
accounting-tz calendar day"), so a debt created near the Asia/Shanghai midnight anchors its
schedule on the date the user perceives as建账日, not the UTC date.
"""

from __future__ import annotations

import calendar
from datetime import date

from app.config import get_settings
from app.models import Debt
from app.services.time_service import ensure_utc, safe_zone


def _add_months(start: date, months: int) -> date:
    """``start`` shifted forward by ``months`` calendar months, clamping the day to the target
    month's length (e.g. Jan 31 + 1 month → Feb 28/29). Pure date arithmetic."""
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def installment_payoff_date(debt: Debt) -> date | None:
    """The contractual payoff date of an installment debt, or ``None`` when it has no schedule.

    ``None`` unless the debt is ``debt_kind == 'installment'`` AND carries a schedule. The
    ``debt_kind`` gate is what makes the schedule columns truly INERT after a reclassification away
    from installment (``set_debt_kind`` only flips ``debt_kind``, leaving the columns populated): a
    now-``revolving`` debt must not report a stale installment payoff or be miscounted as a scheduled
    installment in the goal KPI. Independent of how many periods have already been paid: the schedule
    END is fixed at creation, so partial progress moves the "已还 N/M 期" counter, not the date.
    """
    if (
        debt.debt_kind != "installment"
        or debt.installment_count is None
        or debt.installment_period_months is None
    ):
        return None
    start = ensure_utc(debt.created_at).astimezone(
        safe_zone(get_settings().ocr_default_timezone)
    ).date()
    return _add_months(start, debt.installment_count * debt.installment_period_months)


def installment_paid_count(debt: Debt, *, paid: int) -> int | None:
    """How many whole standard periods of an installment debt have been repaid, or ``None``.

    DERIVED, never stored: the count is ``floor(paid / per_period)`` clamped to the total期数, where
    ``per_period = principal // installment_count`` (integer floor). Storing it would only invite a
    stale copy that disagrees with the repayment facts — ``paid`` already folds every non-voided
    ``Repayment`` (``compute_paid``), and ``installment_count``/``principal`` are at-rest, so the
    progress is always reconstructable. This is the SINGLE source the per-Debt
    ``DebtResponse.installment_paid_count`` (and any future progress UI) reads from.

    Three load-bearing choices:
    * **``paid`` over ``remaining`` for the numerator, ORIGINAL ``principal`` for the denominator.**
      ``remaining`` nets adjustments and forgiveness; a forgiveness reduces ``remaining`` without any
      cash, so dividing it would falsely advance the "已还 N/M 期" counter. ``paid`` is real money
      repaid — the honest period 口径. The denominator is the ORIGINAL ``principal_amount_cents`` for
      the same reason: a standard period is a fixed slice of the original obligation. Like the payoff
      DATE, paid_count therefore tracks the ORIGINAL contract and is independent of any later
      ``DebtAdjustment`` — an out-of-schedule adjustment is extra debt owed separately, not a
      re-amortization of the period size. One consequence to handle at the display layer: an
      obligation-RAISING adjustment can make this read N/N (all original installments paid) while
      ``remaining`` is still > 0. The UI must therefore gate any "已还清/done" wording on the cleared
      STATUS, never on ``paid_count == installment_count``.
    * **floor + clamp.** Floor = "已还满几个标准期" (a half-paid period does not count). The
      ``min(..., installment_count)`` cap stops an over-repayment or positive adjustment from
      reporting progress beyond the total期数.
    * **same ``debt_kind`` gate as the payoff date.** ``None`` unless ``debt_kind == 'installment'``
      with a schedule, so the count goes INERT after a reclassification away from installment
      (``set_debt_kind`` leaves the columns populated). ``installment_period_months`` is irrelevant
      to the count — only ``installment_count`` gates it (the ``ck_debts_installment_valid`` CHECK
      keeps count and period paired, so a set count implies a set period anyway).
    """
    if debt.debt_kind != "installment" or debt.installment_count is None:
        return None
    per_period = int(debt.principal_amount_cents) // debt.installment_count
    if per_period == 0:
        # Degenerate input (principal < 期数): no whole standard period exists. Guard the divide
        # (a ZeroDivisionError would surface as a 500) and report no progress rather than crash.
        return 0
    return min(paid // per_period, debt.installment_count)
