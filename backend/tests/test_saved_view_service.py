"""Saved queries retain intent across new facts and tag identity changes."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, Ledger, LedgerMember, Tag
from app.services.saved_view_service import (
    create_view,
    delete_view,
    list_views,
    resolve_live_tag_public_id,
    resolve_view_query,
    update_view,
)
from app.services.time_service import now_utc


def _owner_id(db):
    owner_id = db.scalar(select(Ledger.owner_account_id)
        .join(LedgerMember, LedgerMember.ledger_id == Ledger.ledger_id)
        .where(Ledger.ledger_id == "owner", LedgerMember.account_id == Ledger.owner_account_id,
               LedgerMember.role == "owner", LedgerMember.disabled_at.is_(None)))
    assert owner_id is not None
    return owner_id


def _definition(**overrides):
    return {**{"name": "九月旅行", "month_mode": "fixed", "month": "2026-09", "filter": "",
               "tag_public_id": None, "home_currency_code": "JPY"}, **overrides}


@pytest.mark.parametrize("month", ["0000-01", "9999-12", "2026-13"])
def test_fixed_view_rejects_months_the_original_financial_query_cannot_read(identity, month):  # noqa: ARG001
    with SessionLocal() as db:
        owner_id = _owner_id(db)
        with pytest.raises(AppError) as exc:
            create_view(db, tenant_id="owner", actor_account_id=owner_id,
                        idempotency_key=str(uuid4()), **_definition(month=month))
        assert exc.value.error == "invalid_request"
        db.rollback()
        assert list_views(db, tenant_id="owner", actor_account_id=owner_id) == []


def test_saved_view_replay_is_original_receipt_and_tag_identity_needs_repair(identity):  # noqa: ARG001
    with SessionLocal() as db:
        owner_id = _owner_id(db)
        tag = Tag(tenant_id="owner", name="旅行", key="旅行")
        db.add(tag)
        db.commit()
        tag_id = resolve_live_tag_public_id(db, tenant_id="owner", actor_account_id=owner_id, tag_name="旅行")
        key = str(uuid4())
        definition = _definition(tag_public_id=tag_id)
        original = create_view(db, tenant_id="owner", actor_account_id=owner_id,
                               idempotency_key=key, **definition)
        assert resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                                  public_id=original.public_id) == {
            "ledger_id": "owner", "month": "2026-09", "tag": "旅行", "home_currency_code": "JPY",
        }
        tag.name = "假期"
        tag.key = "假期"
        db.commit()
        assert resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                                  public_id=original.public_id)["tag"] == "假期"
        renamed = update_view(db, tenant_id="owner", actor_account_id=owner_id,
            public_id=original.public_id, expected_row_version=original.row_version,
            **_definition(name="我的旅行", tag_public_id=tag_id))
        assert renamed.row_version == original.row_version + 1
        assert create_view(db, tenant_id="owner", actor_account_id=owner_id,
                           idempotency_key=key, **definition) == original
        tag.deleted_at = now_utc()
        db.commit()
        assert list_views(db, tenant_id="owner", actor_account_id=owner_id)[0].repair_reason == \
            "saved_view_tag_repair_required"
        with pytest.raises(AppError) as exc:
            resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                               public_id=original.public_id)
        assert exc.value.error == "saved_view_tag_repair_required"
        db.rollback()
        assert create_view(db, tenant_id="owner", actor_account_id=owner_id,
                           idempotency_key=key, **definition) == original
        tag.deleted_at = None
        db.commit()
        assert resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                                  public_id=original.public_id)["tag"] == "假期"
        tag.deleted_at = now_utc()
        db.commit()
        repaired = update_view(db, tenant_id="owner", actor_account_id=owner_id,
            public_id=original.public_id, expected_row_version=renamed.row_version,
            **_definition(name="我的旅行", tag_public_id=None))
        assert repaired.repair_reason is None and repaired.tag_public_id is None
        assert "tag" not in resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                                                public_id=original.public_id)


def test_saved_view_shared_read_viewer_denied_write_and_occ(identity):  # noqa: ARG001
    with SessionLocal() as db:
        owner_id = _owner_id(db)
        viewer = Account(display_name="只读家人")
        db.add(viewer)
        db.flush()
        db.add(LedgerMember(ledger_id="owner", account_id=viewer.id, role="viewer"))
        db.commit()
        created = create_view(db, tenant_id="owner", actor_account_id=owner_id,
            idempotency_key=str(uuid4()), **_definition(month_mode="current", month="",
                filter="missing_accounting_date"))
        assert created.month_mode == "current" and created.month is None
        assert list_views(db, tenant_id="owner", actor_account_id=viewer.id)[0].public_id == created.public_id
        query = resolve_view_query(db, tenant_id="owner", actor_account_id=viewer.id,
                                   public_id=created.public_id)
        assert query == {"ledger_id": "owner", "filter": "missing_accounting_date",
                         "home_currency_code": "JPY"}
        with pytest.raises(AppError) as exc:
            delete_view(db, tenant_id="owner", actor_account_id=viewer.id,
                        public_id=created.public_id, expected_row_version=created.row_version)
        assert exc.value.error == "permission_denied"
        db.rollback()
        with pytest.raises(AppError) as exc:
            create_view(db, tenant_id="owner", actor_account_id=owner_id,
                idempotency_key=str(uuid4()), **_definition())
        assert exc.value.error == "saved_view_conflict"
        db.rollback()
        changed = update_view(db, tenant_id="owner", actor_account_id=owner_id,
            public_id=created.public_id, expected_row_version=created.row_version,
            **_definition(name="缺少账务日期", month_mode="current", month=None,
                          filter="missing_accounting_date"))
        with pytest.raises(AppError) as exc:
            delete_view(db, tenant_id="owner", actor_account_id=owner_id,
                        public_id=created.public_id, expected_row_version=created.row_version)
        assert exc.value.error == "state_conflict"
        db.rollback()
        with pytest.raises(AppError) as exc:
            list_views(db, tenant_id="owner", actor_account_id=999999)
        assert exc.value.error == "ledger_not_found"
        db.rollback()
        delete_view(db, tenant_id="owner", actor_account_id=owner_id,
                    public_id=created.public_id, expected_row_version=changed.row_version)
        assert list_views(db, tenant_id="owner", actor_account_id=viewer.id) == []


def test_current_month_is_resolved_from_ledger_calendar_each_time(identity, monkeypatch):  # noqa: ARG001
    with SessionLocal() as db:
        owner_id = _owner_id(db)
        monkeypatch.setattr("app.services.ledger_calendar_service.now_utc",
                            lambda: datetime(2026, 9, 15, 12, tzinfo=UTC))
        current = create_view(db, tenant_id="owner", actor_account_id=owner_id,
            idempotency_key=str(uuid4()),
            **_definition(name="当前月", month_mode="current", month=None))
        fixed = create_view(db, tenant_id="owner", actor_account_id=owner_id,
            idempotency_key=str(uuid4()), **_definition(name="固定九月"))
        assert resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                                  public_id=current.public_id)["month"] == "2026-09"
        assert resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                                  public_id=fixed.public_id)["month"] == "2026-09"
        monkeypatch.setattr("app.services.ledger_calendar_service.now_utc",
                            lambda: datetime(2026, 10, 15, 12, tzinfo=UTC))
        assert resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                                  public_id=current.public_id)["month"] == "2026-10"
        assert resolve_view_query(db, tenant_id="owner", actor_account_id=owner_id,
                                  public_id=fixed.public_id)["month"] == "2026-09"


def test_create_retry_rejects_different_intent_or_actor_and_does_not_revive_deleted_view(identity):  # noqa: ARG001
    with SessionLocal() as db:
        owner_id = _owner_id(db)
        member = Account(display_name="可编辑家人")
        db.add(member)
        db.flush()
        member_id = member.id
        db.add(LedgerMember(ledger_id="owner", account_id=member_id, role="member"))
        db.commit()
        key = str(uuid4())
        original = create_view(db, tenant_id="owner", actor_account_id=owner_id,
                               idempotency_key=key, **_definition())
        with pytest.raises(AppError) as exc:
            create_view(db, tenant_id="owner", actor_account_id=owner_id,
                        idempotency_key=key, **_definition(name="另一个意图"))
        assert exc.value.error == "idempotency_key_reused"
        db.rollback()
        with pytest.raises(AppError) as exc:
            create_view(db, tenant_id="owner", actor_account_id=member_id,
                        idempotency_key=key, **_definition())
        assert exc.value.error == "idempotency_key_reused"
        db.rollback()
        assert list_views(db, tenant_id="owner", actor_account_id=owner_id) == [original]
        delete_view(db, tenant_id="owner", actor_account_id=owner_id,
                    public_id=original.public_id, expected_row_version=original.row_version)
        assert list_views(db, tenant_id="owner", actor_account_id=owner_id) == []
        assert create_view(db, tenant_id="owner", actor_account_id=owner_id,
                           idempotency_key=key, **_definition()) == original
        assert list_views(db, tenant_id="owner", actor_account_id=owner_id) == []


def test_second_ledger_member_cannot_cross_view_scope_or_read_after_revocation(identity):  # noqa: ARG001
    with SessionLocal() as db:
        owner_id = _owner_id(db)
        foreign_owner = Account(display_name="另一本拥有者")
        member = Account(display_name="两本账本成员")
        db.add_all([foreign_owner, member])
        db.flush()
        member_id = member.id
        other_id = "saved_view_other"
        db.add(Ledger(ledger_id=other_id, name="另一本账本", owner_account_id=foreign_owner.id))
        owner_membership = LedgerMember(ledger_id="owner", account_id=member_id, role="member")
        db.add_all([owner_membership,
            LedgerMember(ledger_id=other_id, account_id=foreign_owner.id, role="owner"),
            LedgerMember(ledger_id=other_id, account_id=member_id, role="member")])
        db.commit()
        original = create_view(db, tenant_id="owner", actor_account_id=owner_id,
                               idempotency_key=str(uuid4()), **_definition())
        assert resolve_view_query(db, tenant_id="owner", actor_account_id=member_id,
                                  public_id=original.public_id)["ledger_id"] == "owner"
        assert list_views(db, tenant_id=other_id, actor_account_id=member_id) == []
        with pytest.raises(AppError) as exc:
            resolve_view_query(db, tenant_id=other_id, actor_account_id=member_id,
                               public_id=original.public_id)
        assert exc.value.error == "saved_view_not_found"
        db.rollback()
        with pytest.raises(AppError) as exc:
            update_view(db, tenant_id=other_id, actor_account_id=member_id,
                public_id=original.public_id, expected_row_version=original.row_version,
                **_definition(name="越界修改"))
        assert exc.value.error == "saved_view_not_found"
        db.rollback()
        with pytest.raises(AppError) as exc:
            delete_view(db, tenant_id=other_id, actor_account_id=member_id,
                        public_id=original.public_id, expected_row_version=original.row_version)
        assert exc.value.error == "saved_view_not_found"
        db.rollback()
        assert list_views(db, tenant_id="owner", actor_account_id=owner_id) == [original]
        owner_membership.disabled_at = now_utc()
        db.commit()
        with pytest.raises(AppError) as exc:
            resolve_view_query(db, tenant_id="owner", actor_account_id=member_id,
                               public_id=original.public_id)
        assert exc.value.error == "ledger_not_found"
        db.rollback()
        assert list_views(db, tenant_id="owner", actor_account_id=owner_id) == [original]
