"""Publish an explicit agreement revision; no future Expense or additional Debt."""
from uuid import uuid4

from sqlalchemy import select

from app.errors import AppError
from app.models import AccountMovement, InstallmentAgreement, InstallmentDraw, InstallmentPeriod
from app.services.funds_commands import claim_funds, finish_funds, replay_funds, require_account_version
from app.services.funds_query import get_account
from app.services.installment_query import active_agreements, draw_balances
from app.services.ledger_calendar_service import current_ledger_date


def save_installments(db, *, auth, public_id, payload, key):
    claim = claim_funds(db, auth, payload, key, "save_installment_agreement", public_id)
    if claim is None:
        return replay_funds(db, auth, key)
    account = get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=public_id, lock=True)
    require_account_version(account, payload.expected_row_version)
    if account.kind != "credit" or not account.balance_known:
        raise AppError("invalid_request", "请先核对信用账户的期初，再记录已成立的分期合约。", status_code=422)
    if payload.agreed_on > current_ledger_date(db, ledger_id=account.tenant_id):
        raise AppError("invalid_request", "只记录已经成立的合约，尚未办理的分期保留为输入。", status_code=422)
    active = active_agreements(db, account.id)
    previous = next((row for row in active if row.public_id == payload.supersedes_public_id), None)
    if payload.supersedes_public_id and previous is None:
        raise AppError("state_conflict", "原合约已变化，请核对最新版本；原输入保留。", status_code=409)
    selected = set(payload.draw_public_ids)
    draws = list(db.scalars(select(AccountMovement).where(AccountMovement.account_id == account.id,
        AccountMovement.public_id.in_(selected), AccountMovement.amount_minor < 0, AccountMovement.reversal_of_id.is_(None))))
    if len(selected) != len(payload.draw_public_ids) or len(draws) != len(selected):
        raise AppError("invalid_request", "请从本账户选择不重复的原信用使用记录。", status_code=422)
    occupied = db.scalar(select(InstallmentDraw.id).where(InstallmentDraw.movement_id.in_([row.id for row in draws]),
        InstallmentDraw.agreement_id.in_([row.id for row in active if row != previous])).limit(1))
    if occupied:
        raise AppError("installment_source_in_use", "所选本金已在其他生效合约中，不能再次安排。", status_code=409)
    remaining = draw_balances(db, account.id)
    balances = {row.id: remaining.get(row.id, 0) for row in draws}
    if any(value <= 0 for value in balances.values()) or sum(balances.values()) != sum(row.principal_minor for row in payload.periods):
        raise AppError("installment_amount_mismatch", "逐期本金合计必须等于所选记录的当前未偿本金；不会新增欠款。", status_code=422)
    dates = [row.due_on for row in payload.periods]
    if dates != sorted(dates) or any(day < payload.agreed_on for day in dates):
        raise AppError("invalid_request", "请按合约填写不早于成立日期、依次排列的到期日。", status_code=422)
    agreement = InstallmentAgreement(account_id=account.id, series_id=previous.series_id if previous else str(uuid4()),
        revision=previous.revision + 1 if previous else 1, supersedes_id=previous.id if previous else None,
        name=payload.name, source=payload.source, agreed_on=payload.agreed_on, actor_account_id=auth.account_id)
    db.add(agreement)
    db.flush()
    db.add_all([InstallmentDraw(agreement_id=agreement.id, movement_id=row.id, principal_minor=balances[row.id]) for row in draws])
    db.add_all([InstallmentPeriod(agreement_id=agreement.id, position=index + 1, **period.model_dump()) for index, period in enumerate(payload.periods)])
    account.row_version += 1
    return finish_funds(db, auth, claim, account)
