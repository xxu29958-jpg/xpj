from __future__ import annotations

import pytest

from app.errors import AppError
from app.services import permission_service
from app.tenants import AuthContext


def _ctx(*, scope: str, role: str) -> AuthContext:
    return AuthContext(
        account_id=1,
        account_name="我",
        ledger_id="owner",
        ledger_name="我的小票夹",
        device_id=1,
        device_name="pytest",
        role=role,
        scope=scope,
    )


def test_app_roles_define_business_permissions() -> None:
    owner = _ctx(scope="app", role="owner")
    member = _ctx(scope="app", role="member")
    viewer = _ctx(scope="app", role="viewer")

    assert permission_service.can_read(owner)
    assert permission_service.can_write_expense(owner)
    assert permission_service.can_write_expense(member)
    assert not permission_service.can_write_expense(viewer)
    assert permission_service.can_create_pending_expense(owner)
    assert permission_service.can_create_pending_expense(member)
    assert not permission_service.can_create_pending_expense(viewer)

    assert permission_service.can_manage_members(owner)
    assert permission_service.can_manage_ledger(owner)
    assert permission_service.can_manage_upload_links(owner)
    assert not permission_service.can_manage_members(member)
    assert not permission_service.can_manage_ledger(viewer)


def test_admin_scope_is_maintenance_not_ledger_business_role() -> None:
    admin_owner = _ctx(scope="admin", role="owner")

    assert not permission_service.can_read(admin_owner)
    assert not permission_service.can_write_expense(admin_owner)
    assert not permission_service.can_create_pending_expense(admin_owner)
    assert not permission_service.can_manage_members(admin_owner)
    assert not permission_service.can_manage_ledger(admin_owner)
    assert not permission_service.can_manage_upload_links(admin_owner)
    assert permission_service.can_use_admin_maintenance(admin_owner)

    with pytest.raises(AppError) as denied:
        permission_service.require_write_expense(admin_owner)
    assert denied.value.status_code == 403

    permission_service.require_admin_maintenance(admin_owner)


def test_upload_scope_can_only_create_pending_expenses() -> None:
    upload_owner = _ctx(scope="upload", role="owner")
    upload_viewer = _ctx(scope="upload", role="viewer")

    assert not permission_service.can_read(upload_owner)
    assert not permission_service.can_write_expense(upload_owner)
    assert permission_service.can_create_pending_expense(upload_owner)
    assert not permission_service.can_create_pending_expense(upload_viewer)

    with pytest.raises(AppError) as denied:
        permission_service.require_write_expense(upload_owner)
    assert denied.value.status_code == 403

    permission_service.require_create_pending_expense(upload_owner)


def test_app_scope_cannot_use_admin_maintenance_guard() -> None:
    owner = _ctx(scope="app", role="owner")

    with pytest.raises(AppError) as denied:
        permission_service.require_admin_maintenance(owner)
    assert denied.value.status_code == 403
