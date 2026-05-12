"""Family-ledger permission service (v0.4-beta1).

Single source of truth for role-based access control. All write/admin
routes MUST call one of the ``require_*`` guards. Defense-in-depth: even
if a route forgets to call this, ``(ledger_id, account_id)`` filtering at
the service layer still isolates data, but never rely on that alone.

Roles (see docs/DECISIONS/0022-family-ledger-permission-model.md):

* ``owner``  — full control: members, invites, ledger metadata, all writes
* ``member`` — read + write expenses, no member/invite/admin actions
* ``viewer`` — read only

Helper functions return ``bool`` for UI hints; ``require_*`` raises
``AppError`` with HTTP 403 for enforcement.
"""

from __future__ import annotations

from app.errors import AppError
from app.tenants import AuthContext


ROLE_OWNER = "owner"
ROLE_MEMBER = "member"
ROLE_VIEWER = "viewer"

ROLES_VALID = frozenset({ROLE_OWNER, ROLE_MEMBER, ROLE_VIEWER})
ROLES_INVITABLE = frozenset({ROLE_MEMBER, ROLE_VIEWER})
ROLES_WRITE = frozenset({ROLE_OWNER, ROLE_MEMBER})
ROLES_MANAGE = frozenset({ROLE_OWNER})


def is_valid_role(role: str) -> bool:
    return role in ROLES_VALID


def is_invitable_role(role: str) -> bool:
    return role in ROLES_INVITABLE


def can_read(ctx: AuthContext) -> bool:
    return ctx.role in ROLES_VALID


def can_write_expense(ctx: AuthContext) -> bool:
    if ctx.scope == "admin":
        return True
    return ctx.role in ROLES_WRITE


def can_manage_members(ctx: AuthContext) -> bool:
    if ctx.scope == "admin":
        return True
    return ctx.role in ROLES_MANAGE


def can_manage_ledger(ctx: AuthContext) -> bool:
    if ctx.scope == "admin":
        return True
    return ctx.role in ROLES_MANAGE


def can_manage_upload_links(ctx: AuthContext) -> bool:
    if ctx.scope == "admin":
        return True
    return ctx.role in ROLES_MANAGE


def _deny(message_key: str = "permission_denied", message: str | None = None) -> None:
    raise AppError(message_key, message=message, status_code=403)


def require_write_expense(ctx: AuthContext) -> None:
    if not can_write_expense(ctx):
        _deny(message="当前角色为只读，无法修改账本。")


def require_manage_members(ctx: AuthContext) -> None:
    if not can_manage_members(ctx):
        _deny()


def require_manage_ledger(ctx: AuthContext) -> None:
    if not can_manage_ledger(ctx):
        _deny()


def require_manage_upload_links(ctx: AuthContext) -> None:
    if not can_manage_upload_links(ctx):
        _deny()
