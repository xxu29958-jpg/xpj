"""One atomic owner for cash-purpose assignments; actual financial facts stay independent."""
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    ApiIdempotencyKey,
    EnvelopeAllocation,
    EnvelopeBook,
    EnvelopeRevision,
    EnvelopeSource,
    FinancialAccount,
    Ledger,
)
from app.schemas.envelopes import EnvelopeReceipt, EnvelopeSave, EnvelopeSummary, EnvelopesView
from app.services.currency_binding_service import require_runtime_home_currency_code, resolve_write_capability
from app.services.currency_common import minor_amount_label
from app.services.envelope_query import envelopes_view
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.permission_service import require_write_expense
from app.services.session_credential_lock import lock_and_revalidate_mutation_actor
from app.services.spending_contract_service import clean_month
from app.services.time_service import now_utc
from app.tenants import AuthContext


def _lock_sources(db: Session, auth: AuthContext, payload: EnvelopeSave) -> list[FinancialAccount]:
    previous = set(db.scalars(select(EnvelopeSource.account_id).where(EnvelopeSource.tenant_id == auth.tenant_id)))
    rows = list(db.scalars(select(FinancialAccount).where(FinancialAccount.tenant_id == auth.tenant_id,
        or_(FinancialAccount.id.in_(previous), FinancialAccount.public_id.in_(payload.account_public_ids)))
        .order_by(FinancialAccount.id).with_for_update()))
    selected = set(payload.account_public_ids)
    if len(selected) != len(payload.account_public_ids) or selected - {row.public_id for row in rows}:
        raise AppError("fund_account_not_found", "所选资金账户不在当前账本，请保留输入重新核对。", status_code=404)
    for row in rows:
        changed = (row.id in previous) != (row.public_id in selected)
        if changed and row.owner_account_id != auth.account_id:
            raise AppError("permission_denied", "只有账户所有者可以加入或移出信封资金池。", status_code=403)
        if row.public_id in selected:
            _review_source(row, payload, new=row.id not in previous)
    return [row for row in rows if row.public_id in selected]


def _review_source(row: FinancialAccount, payload: EnvelopeSave, *, new: bool) -> None:
    if row.visibility != "ledger" or row.kind == "credit" or (new and row.archived_at is not None):
        raise AppError("invalid_request", "信封资金须来自本账本可见的现金、储蓄卡或余额账户；信用额度不能充当现金。", status_code=422)
    if payload.account_row_versions.get(row.public_id) != row.row_version:
        raise AppError("state_conflict", "资金账户已有新变动，请保留分配金额并重新核对最新余额。", status_code=409)


def _review_allocations(before: EnvelopesView, payload: EnvelopeSave) -> bool:
    existing = {row.purpose: row for row in before.purposes}
    if set(payload.allocations) - set(existing) or {key for key, row in existing.items() if row.funded} - set(payload.allocations):
        raise AppError("state_conflict", "用途已变化，请保留金额并重新核对；调整为零可以释放原用途的资金。", status_code=409)
    return all(value <= existing[key].allocated_minor for key, value in payload.allocations.items())


def _review_capacity(before: EnvelopesView, after: EnvelopesView, *, only_releases: bool) -> None:
    if only_releases and after.reserved_minor == 0:
        return
    if after.unassigned_minor is None:
        if not only_releases:
            raise AppError("envelope_cash_unknown", "余额、账务日期或汇率尚未核对，暂不能增加分配；原输入已保留。", status_code=409)
        return
    previous_shortfall = max(0, -(before.unassigned_minor or 0))
    if after.unassigned_minor < -previous_shortfall and not (only_releases and before.unassigned_minor is None):
        shortage = minor_amount_label(-after.unassigned_minor, after.home_currency_code)
        raise AppError("envelope_cash_insufficient", f"这些用途还差 {shortage} 现金。请减少分配或补记实际到账；收入计划和信用额度不能补足现金。", status_code=409)


def _apply(db: Session, auth: AuthContext, month: str, payload: EnvelopeSave) -> EnvelopesView:
    # Serialize assignments across months: the same cash cannot be promised twice.
    db.scalar(select(Ledger).where(Ledger.ledger_id == auth.tenant_id).with_for_update())
    book = db.get(EnvelopeBook, auth.tenant_id)
    version = book.row_version if book else 0
    home = book.home_currency_code if book else require_runtime_home_currency_code(db)
    if (payload.expected_row_version, payload.home_currency_code) != (version, home):
        raise AppError("state_conflict", "另一端已调整信封或币种，请保留原输入并重新核对。", status_code=409)
    sources = _lock_sources(db, auth, payload)
    before = envelopes_view(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id, month=month)
    only_releases = _review_allocations(before, payload)
    if book is None:
        book = EnvelopeBook(tenant_id=auth.tenant_id, home_currency_code=home)
        db.add(book)
    book.row_version, book.updated_at = version + 1, now_utc()
    db.flush()
    _replace_assignments(db, auth.tenant_id, month, sources, payload)
    after = envelopes_view(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id, month=month)
    _review_capacity(before, after, only_releases=only_releases)
    db.add(EnvelopeRevision(tenant_id=auth.tenant_id, row_version=book.row_version, actor_account_id=auth.account_id,
        month=month, reason=payload.reason, allocation_snapshot={"home_currency_code": home,
            "account_public_ids": payload.account_public_ids, "allocations": payload.allocations}))
    return after


def _replace_assignments(db: Session, tenant_id: str, month: str, sources: list[FinancialAccount], payload: EnvelopeSave) -> None:
    db.execute(delete(EnvelopeSource).where(EnvelopeSource.tenant_id == tenant_id))
    db.execute(delete(EnvelopeAllocation).where(EnvelopeAllocation.tenant_id == tenant_id, EnvelopeAllocation.month == month))
    db.add_all(EnvelopeSource(tenant_id=tenant_id, account_id=row.id) for row in sources)
    db.add_all(EnvelopeAllocation(tenant_id=tenant_id, month=month, purpose=key, allocated_minor=value)
               for key, value in payload.allocations.items())
    db.flush()


def save_envelopes(db: Session, *, auth: AuthContext, month: str, payload: EnvelopeSave, key: str) -> EnvelopeReceipt:
    month = clean_month(month)
    try:
        claim = _claim(db, auth, month, payload, key)
        if claim is None:
            return _receipt(db, auth, key)
        result = EnvelopeReceipt.model_validate(EnvelopeSummary.model_validate(
            _apply(db, auth, month, payload).model_dump()).model_dump())
        mark_idempotency_succeeded(db, claim, resource_type="envelope_book", resource_id=auth.tenant_id,
                                  response_body=result.model_dump(mode="json"))
        db.commit()
        return result
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise


def _claim(db: Session, auth: AuthContext, month: str, payload: EnvelopeSave, key: str) -> ApiIdempotencyKey | None:
    lock_and_revalidate_mutation_actor(db, auth, actor_account_id=auth.account_id, ledger_id=auth.ledger_id)
    require_write_expense(auth)
    resolve_write_capability(db)
    return claim_idempotent_request(db, tenant_id=auth.tenant_id, idempotency_key=key,
        operation="save_envelopes", target_type="envelope_book", target_id=month,
        body={"actor_account_id": auth.account_id, **payload.model_dump(mode="json", exclude={"expected_row_version"})},
        expected_row_version=payload.expected_row_version)


def _receipt(db: Session, auth: AuthContext, key: str) -> EnvelopeReceipt:
    receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == auth.tenant_id,
                                                      ApiIdempotencyKey.idempotency_key == key))
    return EnvelopeReceipt.model_validate({**EnvelopeSummary.model_validate(receipt.response_body).model_dump(),
        "receipt_revision": receipt.response_body.get("receipt_revision", 1)})


def review_envelopes(db: Session, *, auth: AuthContext, month: str, payload: EnvelopeSave, key: str) -> EnvelopeReceipt | None:
    """Resolve the original key before preparing any fresh version or key."""
    try:
        if _claim(db, auth, clean_month(month), payload, key) is None:
            return _receipt(db, auth, key)
        return None
    finally:
        db.rollback()
