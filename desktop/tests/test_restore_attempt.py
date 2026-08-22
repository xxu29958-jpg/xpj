from __future__ import annotations

from pathlib import Path

from backend_manager.restore_attempt import RestoreAttemptStore

GENERATION = "ticketbox-backup-11111111-1111-4111-8111-111111111111"


def test_restore_attempt_survives_response_loss_and_retires_only_after_confirmation(
    tmp_path: Path,
) -> None:
    store = RestoreAttemptStore(tmp_path)

    first = store.get_or_create(GENERATION)
    resumed = RestoreAttemptStore(tmp_path).get_or_create(GENERATION)
    assert resumed == first

    store.retire_confirmed(GENERATION, first)
    successor = store.get_or_create(GENERATION)
    assert successor != first


def test_restore_attempt_rejects_tampered_binding(tmp_path: Path) -> None:
    store = RestoreAttemptStore(tmp_path)
    attempt = store.get_or_create(GENERATION)
    path = tmp_path / "11111111-1111-4111-8111-111111111111.json"
    path.write_text(
        '{"schema":"ticketbox-restore-attempt-v1","backup_generation":"'
        + GENERATION
        + '","attempt_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}',
        encoding="utf-8",
    )

    try:
        store.retire_confirmed(GENERATION, attempt)
    except RuntimeError:
        pass
    else:
        raise AssertionError("tampered restore-attempt binding was accepted")
