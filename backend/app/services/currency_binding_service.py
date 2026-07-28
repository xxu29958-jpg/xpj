"""ADR-0061 C02 bridge (PR#255 R9): write-time currency-binding drift gate.

``FX_HOME_CURRENCY_CODE`` (env) is the installation home currency's CURRENT
configured value, not the persisted versioned binding of ADR-0061 C02 — the
full answer (a persisted binding row + revision handshake, so a restart can't
silently reinterpret existing facts) belongs to the follow-up 0061 parity
slice. Until it lands, this module is the minimal fail-closed bridge: every
write path that stamps a new fact with the env currency first checks the env
value against the ``home_currency_code`` of ALREADY persisted facts. An empty
installation passes (first record claims the binding); a single shared
currency passes; any disagreement is configuration drift (C02 forbids
hot-switching) and the write is rejected with ``currency_binding_drift``.

Read paths never come here (they degrade via
:func:`app.services.currency_common.home_currency_code_or_none`); a
misconfigured env still raises ``currency_not_supported`` on the write path
before this gate runs.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE
from app.models import (
    Budget,
    Debt,
    Expense,
    Goal,
    MemberRepaymentProposal,
    MonthlyIncomePlan,
    RecurringItem,
)


# Tables that participate in home-currency semantics. Repayments are covered
# by their parent Debt's frozen currency, so they are not queried separately.
# NOTE: the three lookups are unrolled on purpose — a query inside a for-loop
# body trips the codebase audit's N+1 detector.
def assert_currency_binding_consistent(db: Session, home: str) -> None:
    """Fail closed when the env binding drifts from any persisted home currency.

    Empty installation (first record) and full agreement pass; any persisted
    fact whose ``home_currency_code`` differs from ``home`` rejects the write
    (409 ``currency_binding_drift``). Call sites: write entries that stamp a new
    fact with the env currency (``create_debt``, ``create_repayment_proposal``,
    ``apply_currency_payload``, ``create_pending_expense``). ``record_repayment``
    is deliberately NOT gated by this whole-library check: home-integer repayment
    amounts inherit the parent Debt's frozen currency (the Repayment table has no
    ``home_currency_code`` column and the env value is discarded there) — its
    foreign-currency path is instead guarded per-record in ``_repayment`` (R12-C).
    """
    codes: set[str] = set()
    codes.update(db.scalars(select(Debt.home_currency_code).distinct()))
    codes.update(db.scalars(select(Expense.home_currency_code).distinct()))
    codes.update(db.scalars(select(MemberRepaymentProposal.home_currency_code).distinct()))
    if any(code != home for code in codes):
        raise AppError("currency_binding_drift", status_code=409)
    if codes or home == DEFAULT_HOME_CURRENCY_CODE:
        return
    # R12-F：三表皆空的安装若存在**无币种列**的遗留金额行（CNY 时代整数，单位不可判定
    # —— Budget / Goal / MonthlyIncomePlan / RecurringItem），env≠CNY 时不得视为空库放行
    # 首笔绑定（新写按零小数与存量分整数混算）→ currency_binding_unresolved（409）。
    # env==CNY 放行：多币种未发布，存量无绑定行定义上即 CNY 分。查询保持展开式（N+1 审计）。
    if (
        db.scalar(select(Budget.id).limit(1)) is not None
        or db.scalar(select(Goal.id).limit(1)) is not None
        or db.scalar(select(MonthlyIncomePlan.id).limit(1)) is not None
        or db.scalar(select(RecurringItem.id).limit(1)) is not None
    ):
        raise AppError("currency_binding_unresolved", status_code=409)
