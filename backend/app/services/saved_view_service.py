"""Ledger-shared confirmed-stream queries; never a copy of financial results."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, Ledger, LedgerMember, SavedView, Tag
from app.services.currency_common import normalize_currency_code
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.ledger_calendar_service import current_ledger_month
from app.services.optimistic_concurrency import claim_row_with_token, delete_row_with_token
from app.services.time_service import normalize_month_label, now_utc
from app.tag_text import tag_key

_FILTERS = frozenset({"", "missing_category", "missing_accounting_date"})


@dataclass(frozen=True)
class SavedViewDetail:
    public_id: str
    name: str
    row_version: int
    month_mode: str
    month: str | None
    filter: str
    tag_public_id: str | None
    tag_name: str | None
    home_currency_code: str
    repair_reason: str | None


def _require_ledger_role(db: Session, *, tenant_id: str, actor_account_id: int, write: bool = False) -> None:
    role = db.scalar(
        select(LedgerMember.role)
        .join(Ledger, Ledger.ledger_id == LedgerMember.ledger_id)
        .join(Account, Account.id == LedgerMember.account_id)
        .where(LedgerMember.ledger_id == tenant_id, LedgerMember.account_id == actor_account_id)
        .where(LedgerMember.disabled_at.is_(None), Ledger.archived_at.is_(None), Account.disabled_at.is_(None))
    )
    if role is None:
        raise AppError("ledger_not_found", status_code=404)
    if role not in ({"owner", "member"} if write else {"owner", "member", "viewer"}):
        raise AppError("permission_denied", status_code=403)


def _tag(db: Session, tenant_id: str, public_id: str | None) -> Tag | None:
    if not public_id:
        return None
    return db.scalar(select(Tag).where(Tag.tenant_id == tenant_id, Tag.public_id == public_id))


def resolve_live_tag_public_id(
    db: Session, *, tenant_id: str, actor_account_id: int, tag_name: str | None,
) -> str | None:
    """Bind an existing confirmed-page tag label to a live ledger identity."""
    _require_ledger_role(db, tenant_id=tenant_id, actor_account_id=actor_account_id)
    if not tag_name or not tag_name.strip():
        return None
    row = db.scalar(select(Tag).where(Tag.tenant_id == tenant_id, Tag.key == tag_key(tag_name),
                                       Tag.deleted_at.is_(None)))
    if row is None:
        raise AppError("saved_view_tag_repair_required", status_code=409)
    return row.public_id


def _detail(row: SavedView, tag: Tag | None) -> SavedViewDetail:
    invalid = bool(row.tag_public_id and (tag is None or tag.deleted_at is not None))
    return SavedViewDetail(
        public_id=row.public_id, name=row.name, row_version=row.row_version,
        month_mode=row.month_mode, month=row.month, filter=row.filter,
        tag_public_id=row.tag_public_id, tag_name=tag.name if tag is not None else None,
        home_currency_code=row.home_currency_code,
        repair_reason="saved_view_tag_repair_required" if invalid else None,
    )


def _view(db: Session, tenant_id: str, public_id: str) -> SavedView:
    row = db.scalar(select(SavedView).where(SavedView.tenant_id == tenant_id,
                                             SavedView.public_id == public_id))
    if row is None:
        raise AppError("saved_view_not_found", status_code=404)
    return row


def list_views(db: Session, *, tenant_id: str, actor_account_id: int) -> list[SavedViewDetail]:
    _require_ledger_role(db, tenant_id=tenant_id, actor_account_id=actor_account_id)
    rows = db.execute(select(SavedView, Tag).outerjoin(Tag,
        (Tag.tenant_id == SavedView.tenant_id) & (Tag.public_id == SavedView.tag_public_id))
        .where(SavedView.tenant_id == tenant_id)
        .order_by(SavedView.created_at.desc(), SavedView.id.desc())).all()
    return [_detail(row, tag) for row, tag in rows]


def count_views(db: Session, *, tenant_id: str, actor_account_id: int) -> int:
    _require_ledger_role(db, tenant_id=tenant_id, actor_account_id=actor_account_id)
    return int(db.scalar(select(func.count(SavedView.id)).where(SavedView.tenant_id == tenant_id)) or 0)


def _query_month(month_mode: str, month: str | None, filter: str) -> tuple[str, str | None]:
    """Health queries span periods; ordinary queries retain an explicit month policy."""
    if month_mode not in {"fixed", "current"}:
        raise AppError("invalid_request", "请选择固定月份或账本当前月。", status_code=422)
    if filter not in _FILTERS:
        raise AppError("invalid_request", "已确认流水筛选条件无效。", status_code=422)
    if filter:
        # Existing health filters span all accounting months. Carry no latent
        # month even when the source page submitted its displayed mode.
        return "current", None
    if month_mode == "fixed":
        saved_month = normalize_month_label(month)
        if saved_month is None:
            raise AppError("invalid_request", "请选择有效的固定账务月。", status_code=422)
        return "fixed", saved_month
    return "current", None


def _validated_definition(
    db: Session, *, tenant_id: str, name: str, month_mode: str, month: str | None,
    filter: str, tag_public_id: str | None, home_currency_code: str, check_tag: bool = True,
) -> dict[str, str | None]:
    clean_name = " ".join(name.split())
    name_key = clean_name.casefold()
    if not clean_name or len(clean_name) > 120 or len(name_key) > 120:
        raise AppError("invalid_request", "视图名称需为 1 至 120 个字符。", status_code=422)
    saved_mode, saved_month = _query_month(month_mode, month, filter)
    tag = _tag(db, tenant_id, tag_public_id) if check_tag and tag_public_id else None
    if check_tag and tag_public_id and (tag is None or tag.deleted_at is not None):
        raise AppError("saved_view_tag_repair_required", status_code=409)
    return {"name": clean_name, "name_key": name_key, "month_mode": saved_mode,
            "month": saved_month, "filter": filter, "tag_public_id": tag_public_id or None,
            "home_currency_code": normalize_currency_code(home_currency_code)}


def create_view(
    db: Session, *, tenant_id: str, actor_account_id: int, name: str, month_mode: str,
    month: str | None, filter: str, tag_public_id: str | None,
    home_currency_code: str, idempotency_key: str,
) -> SavedViewDetail:
    _require_ledger_role(db, tenant_id=tenant_id, actor_account_id=actor_account_id, write=True)
    if not idempotency_key or len(idempotency_key) > 64:
        raise AppError("idempotency_key_required", status_code=422)
    definition = _validated_definition(db, tenant_id=tenant_id, name=name, month_mode=month_mode,
                                       month=month, filter=filter, tag_public_id=tag_public_id,
                                       home_currency_code=home_currency_code, check_tag=False)
    operation = "create_saved_view"
    claim = claim_idempotency_key(
        db, tenant_id=tenant_id, idempotency_key=idempotency_key, operation=operation,
        target_type="saved_view", request_fingerprint=fingerprint_request(
            operation=operation, target_id=None,
            body={**definition, "actor_account_id": actor_account_id}, expected_row_version=None,
        ),
    )
    if claim.kind is IdempotencyOutcomeKind.HIT:
        if not claim.row.response_body:
            raise AppError("state_conflict", "原保存已成功，但原回执不可用，请核对视图库。", status_code=409)
        return SavedViewDetail(**claim.row.response_body)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if tag_public_id:
        tag = _tag(db, tenant_id, tag_public_id)
        if tag is None or tag.deleted_at is not None:
            db.rollback()
            raise AppError("saved_view_tag_repair_required", status_code=409)
    existing = db.scalar(select(SavedView.id).where(SavedView.tenant_id == tenant_id,
                                                     SavedView.name_key == definition["name_key"]))
    if existing is not None:
        db.rollback()
        raise AppError("saved_view_conflict", status_code=409)
    row = SavedView(tenant_id=tenant_id, created_by_account_id=actor_account_id, **definition)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("saved_view_conflict", status_code=409) from exc
    result = _detail(row, _tag(db, row.tenant_id, row.tag_public_id))
    mark_idempotency_succeeded(db, claim.row, resource_type="saved_view", resource_id=row.public_id,
                               response_body=asdict(result))
    db.commit()
    return result


def update_view(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str,
    expected_row_version: int, name: str, month_mode: str, month: str | None,
    filter: str, tag_public_id: str | None, home_currency_code: str,
) -> SavedViewDetail:
    _require_ledger_role(db, tenant_id=tenant_id, actor_account_id=actor_account_id, write=True)
    row = _view(db, tenant_id, public_id)
    definition = _validated_definition(db, tenant_id=tenant_id, name=name, month_mode=month_mode,
                                       month=month, filter=filter, tag_public_id=tag_public_id,
                                       home_currency_code=home_currency_code)
    conflicting = db.scalar(select(SavedView.id).where(SavedView.tenant_id == tenant_id,
        SavedView.name_key == definition["name_key"], SavedView.id != row.id))
    if conflicting is not None:
        raise AppError("saved_view_conflict", status_code=409)
    try:
        changed = claim_row_with_token(db, SavedView, pk_id=row.id, tenant_id=tenant_id,
            expected_row_version=expected_row_version,
            set_values={**definition, "updated_at": now_utc()}, synchronize_session=False)
    except IntegrityError as exc:
        db.rollback()
        raise AppError("saved_view_conflict", status_code=409) from exc
    if changed != 1:
        raise AppError("state_conflict", status_code=409)
    db.commit()
    db.expire_all()
    row = _view(db, tenant_id, public_id)
    return _detail(row, _tag(db, row.tenant_id, row.tag_public_id))


def delete_view(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str,
    expected_row_version: int,
) -> None:
    _require_ledger_role(db, tenant_id=tenant_id, actor_account_id=actor_account_id, write=True)
    row = _view(db, tenant_id, public_id)
    if delete_row_with_token(db, SavedView, pk_id=row.id, tenant_id=tenant_id,
                             expected_row_version=expected_row_version) != 1:
        raise AppError("state_conflict", status_code=409)
    db.commit()


def resolve_view_query(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str,
) -> dict[str, str]:
    _require_ledger_role(db, tenant_id=tenant_id, actor_account_id=actor_account_id)
    row = _view(db, tenant_id, public_id)
    query = {"ledger_id": tenant_id, "home_currency_code": row.home_currency_code}
    if row.filter:
        query["filter"] = row.filter
    else:
        query["month"] = row.month if row.month_mode == "fixed" else current_ledger_month(db, ledger_id=tenant_id)
    if row.tag_public_id:
        tag = _tag(db, tenant_id, row.tag_public_id)
        if tag is None or tag.deleted_at is not None:
            raise AppError("saved_view_tag_repair_required", status_code=409)
        query["tag"] = tag.name
    return query
