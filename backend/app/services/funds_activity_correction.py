"""Reverse both sides of the original cash event, preserving later facts."""
from sqlalchemy import select

from app.errors import AppError
from app.models import AccountMovement, FinancialAccount
from app.services.funds_commands import claim_funds, finish_funds, replay_funds, require_account_version
from app.services.funds_fact_service import reverse_movements, validate_movement_date
from app.services.funds_query import get_account


def void_account_activity(db, *, auth, public_id, payload, key):
    claim = claim_funds(db, auth, payload, key, "void_account_activity", public_id)
    if claim is None:
        return replay_funds(db, auth, key)
    account = get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id)
    if db.scalar(select(AccountMovement.id).where(AccountMovement.account_id == account.id,
            AccountMovement.event_public_id == payload.event_public_id)) is None:
        raise AppError("fund_activity_not_found", "这笔资金记录不存在或不属于此账户。", status_code=404)
    rows = list(db.scalars(select(AccountMovement).where(AccountMovement.event_public_id == payload.event_public_id)))
    if any(row.kind not in {"income", "transfer", "loan"} or row.reversal_of_id is not None for row in rows):
        raise AppError("invalid_request", "消费、还款和余额核对请使用各自的更正入口。", status_code=422)
    identifiers = list(db.scalars(select(FinancialAccount.public_id).where(
        FinancialAccount.id.in_({row.account_id for row in rows})).order_by(FinancialAccount.public_id)))
    accounts = {pid: get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=pid, lock=True)
        for pid in identifiers}
    _require_reviewed_event(db, accounts, account, rows, payload)
    reverse_movements(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, rows=rows,
        reason=payload.reason, occurred_on=payload.occurred_on)
    return finish_funds(db, auth, claim, account, affected_account_ids=[row.id for row in accounts.values()])


def _require_reviewed_event(db, accounts, account, rows, payload):
    if set(accounts) != set(payload.account_row_versions):
        raise AppError("state_conflict", "请重新核对这笔记录涉及的全部账户，原输入已保留。", status_code=409)
    require_account_version(account, payload.expected_row_version, allow_archived=True)
    for pid, target in accounts.items():
        require_account_version(target, payload.account_row_versions[pid], allow_archived=True)
        validate_movement_date(db, target, payload.occurred_on)
    if payload.occurred_on < max(row.occurred_on for row in rows):
        raise AppError("invalid_request", "撤销日期不能早于原资金记录。", status_code=422)
    if db.scalar(select(AccountMovement.id).where(AccountMovement.reversal_of_id.in_([row.id for row in rows]))) is not None:
        raise AppError("fund_activity_already_voided", "这笔资金记录已经撤销，请查看原更正记录。", status_code=409)
