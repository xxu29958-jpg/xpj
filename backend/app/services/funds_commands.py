"""Atomic account writes using the existing credential, OCC and receipt boundaries."""
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AccountMovement, ApiIdempotencyKey, CreditFacility, Debt, EnvelopeSource, FinancialAccount
from app.schemas.funds import AccountCreate, FinancialAccountView
from app.services.credit_history_adoption import adopt_existing_debt
from app.services.currency_binding_service import require_runtime_home_currency_code, resolve_write_capability
from app.services.funds_money import valuation
from app.services.funds_query import account_view, get_account
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.ledger_calendar_service import current_ledger_date
from app.services.permission_service import require_write_expense
from app.services.session_credential_lock import lock_and_revalidate_mutation_actor
from app.services.time_service import now_utc
from app.tenants import AuthContext


def claim_funds(db: Session, auth: AuthContext, payload: BaseModel, key: str, operation: str, target: str | None = None):
    lock_and_revalidate_mutation_actor(db, auth, actor_account_id=auth.account_id, ledger_id=auth.ledger_id)
    require_write_expense(auth)
    resolve_write_capability(db)
    body = payload.model_dump(mode="json", exclude={"expected_row_version"})
    if body.get("reviewed_balance_minor") is None:
        # Older repayment corrections had no adoption balance review field.
        body.pop("reviewed_balance_minor", None)
    if not body.get("fee_payments") and not body.get("payer_fee_amount_minor"):
        body.pop("fee_payments", None)
        body.pop("payer_fee_amount_minor", None)
    if body.get("visibility") is None:
        # Retained edits from older clients never changed account visibility.
        body.pop("visibility", None)
    if body.get("source_repayment_draft_id") is None:
        # Old retained account repayments did not carry capture review fields.
        # Keep their original fingerprint so an accepted key remains replayable.
        for name in ("source_repayment_draft_id", "source_amount_basis", "source_review_reason"):
            body.pop(name, None)
    return claim_idempotent_request(db, tenant_id=auth.tenant_id, idempotency_key=key,
        operation=operation, target_type="financial_account", target_id=target,
        body={**body, "actor_account_id": auth.account_id},
        expected_row_version=getattr(payload, "expected_row_version", None))


def replay_funds(db: Session, auth: AuthContext, key: str) -> FinancialAccountView:
    row = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == auth.tenant_id,
        ApiIdempotencyKey.idempotency_key == key))
    # Acceptance survives access changes, but a retained receipt cannot bypass
    # the current account visibility used by ordinary reads.
    get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=row.resource_id)
    result = FinancialAccountView.model_validate(row.response_body)
    result.movements = [movement.model_copy(update={"correction_parts": []}) for movement in result.movements]
    return result


def funds_request_is_unpublished(db, auth, key):
    # Share the command's transaction lock: an uncommitted original request must
    # finish before absence can be used to reopen malformed retained input.
    lock_and_revalidate_mutation_actor(db, auth, actor_account_id=auth.account_id, ledger_id=auth.ledger_id)
    require_write_expense(auth)
    return db.scalar(select(ApiIdempotencyKey.id).where(ApiIdempotencyKey.tenant_id == auth.ledger_id,
        ApiIdempotencyKey.idempotency_key == key)) is None


def finish_funds(db, auth, claim, account):
    db.flush()
    result = account_view(db, account, actor_account_id=auth.account_id, with_movements=True, ledger_id=auth.ledger_id)
    # An accepted receipt is historical; other accounts' current action
    # candidates belong only to an authorized detail read, not durable replay.
    result.movements = [row.model_copy(update={"correction_parts": []}) for row in result.movements]
    mark_idempotency_succeeded(db, claim, resource_type="financial_account", resource_id=account.public_id,
        response_body=result.model_dump(mode="json"))
    db.commit()
    return result


def require_account_version(row, version, *, allow_archived=False):
    if row.row_version != version:
        raise AppError("state_conflict", "账户已变化，请保留原输入并重新核对余额。", status_code=409)
    if row.archived_at is not None and not allow_archived:
        raise AppError("fund_account_archived", "这个资金账户已归档，请选择正在使用的账户。", status_code=409)


def movement(db, auth, account, *, event, component, kind, amount, occurred_on, note, home_amount=None, **source):
    snapshot = source.pop("valuation_snapshot", None)
    if snapshot is None:
        home_amount, snapshot = valuation(db, ledger_id=account.tenant_id, currency=account.currency_code,
            amount_minor=amount, occurred_on=occurred_on)
    row = AccountMovement(tenant_id=account.tenant_id, account_id=account.id, event_public_id=event,
        component_id=component, kind=kind, amount_minor=amount, home_amount_cents=home_amount,
        home_currency_code=require_runtime_home_currency_code(db), occurred_on=occurred_on,
        note=note, actor_account_id=auth.account_id, valuation_snapshot=snapshot, **source)
    db.add(row)
    return row


def create_account(db: Session, *, auth: AuthContext, payload: AccountCreate, key: str) -> FinancialAccountView:
    claim = claim_funds(db, auth, payload, key, "create_financial_account")
    if claim is None:
        return replay_funds(db, auth, key)
    if payload.opening_date > current_ledger_date(db, ledger_id=auth.tenant_id):
        raise AppError("funds_date_outside_coverage", "期初必须来自已经发生的余额核对，不能使用未来日期。", status_code=422)
    row = FinancialAccount(tenant_id=auth.tenant_id, owner_account_id=auth.account_id,
        balance_known=payload.opening_amount_minor is not None,
        **payload.model_dump(exclude={"opening_amount_minor", "credit_terms", "existing_debt"}))
    apply_credit_terms(db, row, payload.credit_terms)
    db.add(row)
    db.flush()
    if payload.existing_debt is not None:
        adopt_existing_debt(db, auth=auth, account=row, payload=payload)
    elif row.kind == "credit":
        _create_credit_facility(db, auth, row, opening=payload.opening_amount_minor)
    if payload.opening_amount_minor is not None:
        amount = payload.opening_amount_minor * (-1 if row.kind == "credit" else 1)
        movement(db, auth, row, event=str(uuid4()), component="opening", kind="opening", amount=amount,
            occurred_on=payload.opening_date, note=payload.opening_source)
    return finish_funds(db, auth, claim, row)


def _create_credit_facility(db: Session, auth: AuthContext, account: FinancialAccount, *, opening: int | None) -> None:
    debt = Debt(tenant_id=auth.tenant_id, owner_account_id=auth.account_id, created_by_account_id=auth.account_id,
        direction="i_owe", counterparty_type="external", counterparty_label=account.name, debt_kind="revolving",
        principal_amount_cents=0, home_currency_code=require_runtime_home_currency_code(db),
        original_currency_code=account.currency_code, original_amount_minor=0, source_type="credit_facility",
        source_id=account.public_id, status="cleared" if opening == 0 else "open")
    db.add(debt)
    db.flush()
    db.add(CreditFacility(account_id=account.id, debt_id=debt.id))


def edit_account(db, *, auth, public_id, payload, key):
    claim = claim_funds(db, auth, payload, key, "edit_financial_account", public_id)
    if claim is None:
        return replay_funds(db, auth, key)
    row = get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=public_id, lock=True)
    if row.owner_account_id != auth.account_id:
        raise AppError("permission_denied", "只有账户所有者可以修改名称或归档账户。", status_code=403)
    require_account_version(row, payload.expected_row_version, allow_archived=True)
    _edit_visibility(db, auth, row, payload.visibility)
    row.name, row.institution, row.tail = payload.name, payload.institution, payload.tail
    if "credit_terms" in payload.model_fields_set:
        apply_credit_terms(db, row, payload.credit_terms)
    row.archived_at = now_utc() if payload.archived else None
    row.row_version += 1
    debt = db.scalar(select(Debt).join(CreditFacility, CreditFacility.debt_id == Debt.id).where(CreditFacility.account_id == row.id))
    if debt is not None:
        debt.counterparty_label = row.name
        debt.row_version += 1
        debt.updated_at = now_utc()
    return finish_funds(db, auth, claim, row)


def _edit_visibility(db, auth, row, visibility):
    if visibility is None or visibility == row.visibility:
        return
    if row.tenant_id != auth.tenant_id:
        raise AppError("invalid_request", "请在创建这个账户的账本内调整可见范围。", status_code=422)
    if visibility == "private" and db.get(EnvelopeSource, row.id) is not None:
        raise AppError("fund_account_in_envelopes", "这个账户正在提供信封资金。请先在信封分配中移出，再改为仅自己可见。", status_code=409)
    row.visibility = visibility


def apply_credit_terms(db, account, terms):
    if terms is None:
        return
    if account.kind != "credit":
        raise AppError("invalid_request", "授信额度和账单规则只适用于信用账户。", status_code=422)
    if terms.observed_on and terms.observed_on > current_ledger_date(db, ledger_id=account.tenant_id):
        raise AppError("invalid_request", "额度查询日期不能在未来。", status_code=422)
    account.credit_limit_minor, account.available_credit_minor = terms.credit_limit_minor, terms.available_credit_minor
    account.credit_observed_on, account.credit_source = terms.observed_on, terms.source
    account.statement_day, account.payment_due_day = terms.statement_day, terms.payment_due_day
