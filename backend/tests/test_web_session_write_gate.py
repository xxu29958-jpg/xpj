"""ADR-0043 P1 regression: a /web session gates writes on the SESSION's role.

``list_console_ledgers`` reports the local account as ``owner`` on its ledgers,
but a paired *viewer* device's Web session must stay read-only
(ENGINEERING_RULES §14). ``_resolve_selected_ledger_id`` stamps the session role
onto the matching option so the shared write-gate
(``_require_selected_ledger_write``) sees ``viewer``, not the console's
``owner``. Without the fix a Web viewer could mutate any /web route.
"""

from __future__ import annotations

import pytest

from app.errors import AppError
from app.routes.web_common import (
    LedgerOption,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
)


def _option(ledger_id: str, role: str, *, name: str = "家庭账本") -> LedgerOption:
    return LedgerOption(
        ledger_id=ledger_id,
        name=name,
        role=role,
        is_default=True,
        pending_count=0,
        confirmed_count=0,
    )


class _SessionRequest:
    """Minimal stand-in for a Request carrying a verified web session."""

    def __init__(self, ledger_id: str, role: str, *, ledger_name: str = "会话账本") -> None:
        auth = type(
            "_Auth",
            (),
            {"ledger_id": ledger_id, "ledger_name": ledger_name, "role": role},
        )()
        self.state = type("_State", (), {"web_session_auth": auth})()


def test_web_session_viewer_cannot_write_even_when_console_lists_owner() -> None:
    options = [
        _option("L1", "owner", name="本地名称"),
        _option("L2", "owner", name="不应公开的账本"),
    ]
    request = _SessionRequest(
        "L1",
        "viewer",
        ledger_name="会话授权账本",
    )

    selected = _resolve_selected_ledger_id(None, None, options, request=request)

    assert selected == "L1"
    assert [(option.ledger_id, option.name, option.role) for option in options] == [
        ("L1", "会话授权账本", "viewer")
    ]
    with pytest.raises(AppError) as exc:
        _require_selected_ledger_write(options, selected)
    assert exc.value.error == "permission_denied"
    assert exc.value.status_code == 403


def test_web_session_member_may_write() -> None:
    options = [_option("L1", "owner"), _option("L2", "owner")]
    request = _SessionRequest("L1", "member")

    selected = _resolve_selected_ledger_id(None, None, options, request=request)

    assert [option.ledger_id for option in options] == ["L1"]
    assert options[0].role == "member"
    _require_selected_ledger_write(options, selected)  # no raise


def test_write_gate_denies_when_ledger_is_not_an_option() -> None:
    """Hardening: a WRITE gate never falls back to options[0]."""
    options = [_option("L1", "owner")]
    with pytest.raises(AppError) as exc:
        _require_selected_ledger_write(options, "L2-not-listed")
    assert exc.value.status_code == 403
