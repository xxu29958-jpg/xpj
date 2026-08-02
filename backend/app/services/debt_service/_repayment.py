"""ADR-0049 §3.1 Repayment: record one committed repayment fact.

Records a *committed* repayment — the creditor's "I received payment" or an
external/owner-side direct entry — and reduces the derived ``remaining`` once
(§3.1 / F6). The debtor's "I paid" path for member Debt is a pending
``MemberRepaymentProposal`` (§3.2 / §5.2 / F5) and is slice 3; this service does
NOT accept ``proposal_id`` and only writes a directly-committable repayment.

Currency (§2.2): a foreign-currency repayment freezes its home ``amount_cents``
from the [[0027]] snapshot for ``paid_at`` (``exchange_rate_pending`` → 409),
sharing the §2.2 freeze with Debt creation via :mod:`_money`.

The §2.1 parent-Debt serialization (FOR UPDATE + bump) and the over-remaining
check (F8) live in the :func:`~app.services.debt_service._serialize.lock_and_fold`
mutate callback, so the overpay check runs from authoritative facts under the
lock.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Debt, Repayment
from app.schemas import RepaymentCreateRequest
from app.services.currency_binding_service import resolve_write_capability
from app.services.currency_common import home_currency_code
from app.services.debt_service._guards import guard_direct_fact_writable
from app.services.debt_service._money import (
    freeze_home_amount,
    validate_home_amount_command,
)
from app.services.debt_service._serialize import lock_and_fold
from app.services.time_service import now_utc


@dataclass
class RecordedRepayment:
    debt: Debt
    repayment_public_id: str


def get_repayment_public_id_for_idempotency(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    idempotency_key: str,
) -> str:
    """Return the committed repayment id for a successful replay."""
    repayment_public_id = db.scalar(
        select(Repayment.public_id)
        .join(Debt, Repayment.debt_id == Debt.id)
        .where(Debt.tenant_id == tenant_id)
        .where(Debt.public_id == public_id)
        .where(Repayment.idempotency_key == idempotency_key)
        .limit(1)
    )
    if repayment_public_id is None:
        raise AppError("repayment_not_found", status_code=404)
    return repayment_public_id


def _guard_repayment_currency_binding(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: RepaymentCreateRequest,
) -> None:
    """Reject FX materialization when the parent and runtime home bindings drift."""

    if payload.original_currency is None and payload.original_amount is None:
        return
    parent_home = db.scalar(
        ledger_scoped_select(Debt, tenant_id)
        .where(Debt.public_id == public_id)
        .with_only_columns(Debt.home_currency_code)
    )
    if parent_home is not None and parent_home != home_currency_code():
        raise AppError("currency_binding_drift", status_code=409)


def record_repayment(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    actor_account_id: int,
    payload: RepaymentCreateRequest,
    idempotency_key: str,
    commit: bool = False,
) -> RecordedRepayment:
    """Record one committed repayment and return the fold-updated parent Debt.

    ``commit=False`` lets the route commit the Repayment insert + parent bump +
    [[0042]] idempotency-success record in one transaction.
    """
    validate_home_amount_command(
        amount_cents=payload.amount_cents,
        original_currency=payload.original_currency,
        original_amount=payload.original_amount,
    )
    resolve_write_capability(db)
    paid_at = payload.paid_at or now_utc()
    # PR#255 R12-C：外币还款的换算按 env home 进行（freeze_home_amount），随后整数按
    # parent debt 的冻结币种折叠 —— payload 带 original 币种字段且 debt.home_currency_code
    # ≠ env 时，换算口径与折叠口径错位（错额或误报 overpay，bot 09:28 P1）→ 按
    # currency_binding_drift 拒（与库级 drift 门同码同 409：都是「配置与已冻结事实不一致」
    # 的写拒绝；无 original 字段=整数透传，record 冻结语义豁免不动）。轻查 parent 冻结
    # 币种于 freeze 之前；debt 不存在时不拦（lock_and_fold 的 404 自会处理）。
    _guard_repayment_currency_binding(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        payload=payload,
    )
    money = freeze_home_amount(
        db,
        tenant_id=tenant_id,
        amount_cents=payload.amount_cents,
        original_currency=payload.original_currency,
        original_amount=payload.original_amount,
        event_time=paid_at,
        amount_error="debt_amount_invalid",
    )
    # The Repayment table has no home_currency_code column (that lives on the
    # parent Debt); drop it from the freeze result.
    money.pop("home_currency_code", None)
    amount_cents = money.pop("amount_cents")

    def _mutate(debt: Debt, remaining_before: int) -> Repayment:
        # §5.2 / §3.5 adverse-interest guard: slice 2 only records committed
        # repayments directly for external/manual Debt (owner-side bookkeeping).
        # Member-Debt repayment stays behind the slice-3 confirmation flow.
        guard_direct_fact_writable(debt)
        # §3.1 / F8: a repayment that would push remaining below 0 is rejected
        # inside the serialized section, never silently clamped.
        if amount_cents > remaining_before:
            raise AppError("debt_overpay_rejected", status_code=422)
        repayment = Repayment(
            debt_id=debt.id,
            amount_cents=amount_cents,
            paid_at=paid_at,
            actor_account_id=actor_account_id,
            proposal_id=None,
            idempotency_key=idempotency_key,
            **money,
        )
        db.add(repayment)
        return repayment

    debt, repayment = lock_and_fold(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        mutate=_mutate,
    )
    if commit:
        db.commit()
        db.refresh(debt)
    return RecordedRepayment(debt=debt, repayment_public_id=repayment.public_id)
