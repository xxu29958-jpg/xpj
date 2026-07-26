"""Desktop app-principal storage contracts."""

from __future__ import annotations

from backend_manager.product_identity import (
    ProductSession,
    _decode_session,
    _encode_session,
    credential_target,
)


def _session() -> ProductSession:
    return ProductSession(
        session_token="tbx-super-secret-token",
        account_name="我",
        ledger_id="owner",
        ledger_name="我的小票夹",
        device_name="小票夹 Desktop",
        role="owner",
        expires_at="2026-10-16T00:00:00Z",
    )


def test_credential_target_is_installation_scoped_and_non_sensitive() -> None:
    first = credential_target("ticketbox-installation-alpha")
    second = credential_target("ticketbox-installation-beta")

    assert first != second
    assert first.startswith("Ticketbox/DesktopAppSession/")
    assert len(first) == len("Ticketbox/DesktopAppSession/") + 32
    assert "installation-alpha" not in first
    assert "installation-beta" not in second


def test_product_session_never_exposes_token_in_repr_or_public_projection() -> None:
    session = _session()

    assert session.session_token not in repr(session)
    assert session.session_token not in str(session.public_projection())
    assert "session_token" not in session.public_projection()


def test_credential_payload_round_trips_without_losing_principal_binding() -> None:
    session = _session()

    decoded = _decode_session(_encode_session(session))

    assert decoded == session
