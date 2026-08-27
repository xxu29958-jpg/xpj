from __future__ import annotations

from pathlib import Path

from ticketbox_lifecycle.runtime import mutex as mutex_module
from ticketbox_lifecycle.runtime.mutex import WindowsFileMutex


def test_windows_file_mutex_holds_one_exclusive_handle_until_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lock_path = tmp_path / "lifecycle.lock"
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        mutex_module,
        "_open_protected_lock_file",
        lambda path: calls.append(("open", path)) or 7,
    )
    monkeypatch.setattr(
        mutex_module,
        "_close_handle",
        lambda handle: calls.append(("close", handle)),
    )

    mutex = WindowsFileMutex(lock_path)
    mutex.acquire()
    mutex.release()
    mutex.release()

    assert calls == [("open", lock_path), ("close", 7)]


def test_windows_mutex_uses_createfile_share_zero_and_no_named_kernel_object() -> None:
    source = Path(mutex_module.__file__).read_text(encoding="utf-8")

    assert "CreateFileW" in source
    assert "_FILE_SHARE_NONE = 0" in source
    assert "_FILE_FLAG_OPEN_REPARSE_POINT" in source
    assert "CreateMutexW" not in source
    assert "Global\\TicketboxLifecycle" not in source
