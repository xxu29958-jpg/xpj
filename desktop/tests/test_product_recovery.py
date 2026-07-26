"""Desktop rebind-recovery storage contracts."""

from __future__ import annotations

from backend_manager.product_recovery import (
    RebindRecovery,
    _decode_recovery,
    _encode_recovery,
    recovery_target,
)


def _recovery() -> RebindRecovery:
    return RebindRecovery(
        activation_attempt_id="12345678-1234-5678-1234-567812345678",
        activation_attempt_secret="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        account_name="我",
        ledger_id="owner",
        ledger_name="我的小票夹",
        device_name="小票夹 Desktop",
        role="owner",
        activation_expires_at="2026-07-26T22:20:00Z",
    )


def test_recovery_target_is_installation_scoped_and_non_sensitive() -> None:
    first = recovery_target("ticketbox-installation-alpha")
    second = recovery_target("ticketbox-installation-beta")

    assert first != second
    assert first.startswith("Ticketbox/DesktopRebindRecovery/")
    assert len(first) == len("Ticketbox/DesktopRebindRecovery/") + 32
    assert "installation-alpha" not in first
    assert "installation-beta" not in second


def test_rebind_recovery_never_exposes_attempt_secret_in_repr() -> None:
    recovery = _recovery()

    assert recovery.activation_attempt_secret not in repr(recovery)
    assert recovery.activation_attempt_id in repr(recovery)


def test_recovery_payload_round_trips_without_losing_attempt_proof() -> None:
    recovery = _recovery()

    decoded = _decode_recovery(_encode_recovery(recovery))

    assert decoded == recovery
