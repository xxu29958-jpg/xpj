from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.services import secure_file  # noqa: E402


def test_initial_runtime_settings_publication_is_create_only(tmp_path: Path) -> None:
    from app.services import runtime_settings_store as store

    target = (tmp_path / "runtime-settings.json").resolve()
    initial = store.RuntimeSettingsProjection("", False)
    conflicting_retry = store.RuntimeSettingsProjection(
        "https://must-not-overwrite.example",
        True,
    )

    assert store.initialize_runtime_settings(
        target,
        initial,
        service_owned=False,
    ) == initial
    assert store.initialize_runtime_settings(
        target,
        conflicting_retry,
        service_owned=False,
    ) == initial
    assert store.read_runtime_settings(target, service_owned=False) == initial


def test_retry_accepts_completed_no_replace_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import runtime_settings_store as store

    target = (tmp_path / "runtime-settings.json").resolve()
    initial = store.RuntimeSettingsProjection("", False)
    publications = 0

    def publish_then_lose_response(
        path: Path,
        text: str,
        *,
        service_owned: bool,
    ) -> None:
        nonlocal publications
        publications += 1
        path.write_bytes(text.encode("utf-8"))
        raise OSError("publication response lost")

    @contextmanager
    def hold(path: Path):
        yield path

    monkeypatch.setattr(
        store,
        "write_protected_file_no_replace",
        publish_then_lose_response,
    )
    monkeypatch.setattr(store, "hold_protected_file_for_read", hold)
    with pytest.raises(OSError, match="response lost"):
        store.initialize_runtime_settings(target, initial, service_owned=False)

    assert store.initialize_runtime_settings(
        target,
        initial,
        service_owned=False,
    ) == initial
    assert publications == 1


def _service_authority() -> tuple[str, dict[str, int]]:
    sid = "S-1-5-80-1-2-3-4-5"
    return sid, {sid: secure_file._FILE_ALL_ACCESS}


def test_service_owned_no_replace_stages_before_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = (tmp_path / "runtime-settings.json").resolve()
    writes: list[tuple[Path, bytes, str | None]] = []
    publications: list[tuple[Path, Path, str, dict[str, int]]] = []
    monkeypatch.setattr(secure_file.os, "name", "nt")
    monkeypatch.setattr(
        secure_file,
        "_windows_service_projection_authority",
        _service_authority,
    )
    monkeypatch.setattr(
        secure_file,
        "_write_windows_protected_file",
        lambda path, payload, *, owner_sid=None: (
            writes.append((path, payload, owner_sid)),
            path.write_bytes(payload),
        ),
    )
    monkeypatch.setattr(
        secure_file,
        "_publish_windows_file_no_replace",
        lambda source, destination, *, owner_sid, access_rules: (
            publications.append((source, destination, owner_sid, access_rules)),
            source.replace(destination),
        ),
    )

    secure_file.write_protected_file_no_replace(
        target,
        "payload",
        service_owned=True,
    )

    assert len(writes) == 1
    staging, payload, owner = writes[0]
    assert staging.parent == target.parent and staging != target
    assert payload == b"payload"
    assert owner == _service_authority()[0]
    assert publications == [
        (staging, target, *_service_authority()),
    ]
    assert target.read_text(encoding="utf-8") == "payload"
    assert list(tmp_path.glob(".runtime-settings.json.*.staging")) == []


@pytest.mark.parametrize(
    "failure_message",
    ("WriteFile failed", "short write", "FlushFileBuffers failed"),
)
def test_failed_staging_write_leaves_no_final_authority_and_can_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_message: str,
) -> None:
    target = (tmp_path / "runtime-settings.json").resolve()
    attempts = 0
    monkeypatch.setattr(secure_file.os, "name", "nt")
    monkeypatch.setattr(
        secure_file,
        "_windows_service_projection_authority",
        _service_authority,
    )

    def write(path: Path, payload: bytes, *, owner_sid: str | None = None) -> None:
        nonlocal attempts
        attempts += 1
        path.write_bytes(payload[:3])
        if attempts == 1:
            raise OSError(failure_message)
        path.write_bytes(payload)

    monkeypatch.setattr(secure_file, "_write_windows_protected_file", write)
    monkeypatch.setattr(
        secure_file,
        "_publish_windows_file_no_replace",
        lambda source, destination, **_kwargs: source.replace(destination),
    )

    with pytest.raises(OSError, match=failure_message):
        secure_file.write_protected_file_no_replace(
            target,
            "payload",
            service_owned=True,
        )
    assert not target.exists()
    assert list(tmp_path.glob(".runtime-settings.json.*.staging")) == []

    secure_file.write_protected_file_no_replace(
        target,
        "payload",
        service_owned=True,
    )
    assert target.read_text(encoding="utf-8") == "payload"


def test_windows_no_replace_is_write_through_and_identity_preserving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (tmp_path / ".settings.staging").resolve()
    destination = (tmp_path / "settings.json").resolve()
    moves: list[tuple[str, str, int]] = []

    @contextmanager
    def hold(
        _path: Path,
        *,
        owner_sids: frozenset[str],
        access_rules: dict[str, int],
    ):
        assert owner_sids == frozenset({_service_authority()[0]})
        assert access_rules == _service_authority()[1]
        yield SimpleNamespace(stat=lambda: SimpleNamespace(st_dev=7, st_ino=11))

    class Kernel:
        @staticmethod
        def MoveFileExW(old: str, new: str, flags: int) -> bool:  # noqa: N802
            moves.append((old, new, flags))
            return True

    monkeypatch.setattr(secure_file, "_hold_windows_protected_file", hold)
    monkeypatch.setattr(secure_file, "_windows_apis", lambda: (object(), Kernel()))
    secure_file._publish_windows_file_no_replace(
        source,
        destination,
        owner_sid=_service_authority()[0],
        access_rules=_service_authority()[1],
    )

    assert moves == [
        (str(source), str(destination), secure_file._MOVEFILE_WRITE_THROUGH)
    ]
