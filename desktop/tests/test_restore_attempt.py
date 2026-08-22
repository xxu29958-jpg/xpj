from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend_manager import restore_attempt
from backend_manager.restore_attempt import RestoreAttemptStore

GENERATION = "ticketbox-backup-11111111-1111-4111-8111-111111111111"


def test_windows_attempt_publication_is_write_through_and_create_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, str, int]] = []

    class MoveFileEx:
        argtypes = None
        restype = None

        def __call__(self, source: str, target: str, flags: int) -> int:
            calls.append((source, target, flags))
            return 1

    class Kernel32:
        MoveFileExW = MoveFileEx()

    monkeypatch.setattr(restore_attempt.ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel32())
    source = tmp_path / "attempt.tmp"
    target = tmp_path / "attempt.json"
    restore_attempt._move_windows_durable_no_replace(source, target)

    assert calls == [(str(source), str(target), restore_attempt._MOVEFILE_WRITE_THROUGH)]


def test_restore_attempt_publication_failure_cannot_return_an_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_publication(_source: Path, _target: Path) -> None:
        raise OSError("durable publication failed")

    monkeypatch.setattr(restore_attempt, "_move_durable_no_replace", fail_publication)
    try:
        RestoreAttemptStore(tmp_path).get_or_create(GENERATION)
    except OSError as exc:
        assert "durable publication failed" in str(exc)
    else:
        raise AssertionError("restore attempt escaped failed durable publication")


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


def test_confirmed_retirement_cleanup_failure_cannot_reclassify_restore_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = RestoreAttemptStore(tmp_path)
    attempt = store.get_or_create(GENERATION)
    canonical = tmp_path / "11111111-1111-4111-8111-111111111111.json"
    real_unlink = Path.unlink

    def fail_tombstone_cleanup(path: Path, *args, **kwargs) -> None:
        if path.suffix == ".retired":
            raise OSError("scanner retained tombstone")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_tombstone_cleanup)

    assert store.retire_confirmed(GENERATION, attempt) == "cleanup_pending"
    assert not canonical.exists()
    assert tuple(tmp_path.glob("*.retired"))

    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert store.cleanup_retired() == "clean"
    assert not tuple(tmp_path.glob("*.retired"))


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
