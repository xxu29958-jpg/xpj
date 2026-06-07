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


def _option(ledger_id: str, role: str) -> LedgerOption:
    return LedgerOption(
        ledger_id=ledger_id,
        name="家庭账本",
        role=role,
        is_default=True,
        pending_count=0,
        confirmed_count=0,
    )


class _SessionRequest:
    """Minimal stand-in for a Request carrying a verified web session."""

    def __init__(self, ledger_id: str, role: str) -> None:
        auth = type("_Auth", (), {"ledger_id": ledger_id, "role": role})()
        self.state = type("_State", (), {"web_session_auth": auth})()


def test_web_session_viewer_cannot_write_even_when_console_lists_owner() -> None:
    options = [_option("L1", "owner")]  # owner-console perspective
    request = _SessionRequest("L1", "viewer")  # paired viewer device

    selected = _resolve_selected_ledger_id(None, None, options, request=request)

    assert selected == "L1"
    assert options[0].role == "viewer", "session role must override the console role"
    with pytest.raises(AppError) as exc:
        _require_selected_ledger_write(options, selected)
    assert exc.value.error == "permission_denied"
    assert exc.value.status_code == 403


def test_web_session_member_may_write() -> None:
    options = [_option("L1", "owner")]
    request = _SessionRequest("L1", "member")

    selected = _resolve_selected_ledger_id(None, None, options, request=request)

    assert options[0].role == "member"
    _require_selected_ledger_write(options, selected)  # no raise


def test_write_gate_denies_when_ledger_is_not_an_option() -> None:
    """Hardening: a WRITE gate never falls back to options[0]."""
    options = [_option("L1", "owner")]
    with pytest.raises(AppError) as exc:
        _require_selected_ledger_write(options, "L2-not-listed")
    assert exc.value.status_code == 403
