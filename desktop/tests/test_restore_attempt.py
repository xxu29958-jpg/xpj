from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
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


def test_restore_attempt_concurrent_creators_converge_on_one_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "11111111-1111-4111-8111-111111111111.json"
    real_exists = Path.exists
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    observations = 0

    def observe_absent_together(path: Path) -> bool:
        nonlocal observations
        if path == target:
            with lock:
                observation = observations
                observations += 1
            if observation < 2:
                barrier.wait(timeout=5)
                return False
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", observe_absent_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = tuple(
            pool.map(
                lambda _index: RestoreAttemptStore(tmp_path).get_or_create(GENERATION),
                range(2),
            )
        )

    assert attempts[0] == attempts[1]
    assert RestoreAttemptStore(tmp_path).get_or_create(GENERATION) == attempts[0]
