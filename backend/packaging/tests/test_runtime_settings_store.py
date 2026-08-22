from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.services import secure_file  # noqa: E402


def test_protected_replace_is_atomic_and_leaves_no_staging_file(tmp_path: Path) -> None:
    target = (tmp_path / "runtime-settings.json").resolve()
    secure_file.write_protected_file_replace(target, "old", service_owned=False)
    secure_file.write_protected_file_replace(target, "new", service_owned=False)

    assert target.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob(".runtime-settings.json.*.staging")) == []


def test_runtime_settings_store_is_closed_canonical_and_replace_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import runtime_settings_store as store

    target = (tmp_path / "runtime-settings.json").resolve()
    publications: list[tuple[Path, str, bool]] = []

    def publish(path: Path, text: str, *, service_owned: bool) -> None:
        publications.append((path, text, service_owned))
        path.write_bytes(text.encode("utf-8"))

    @contextmanager
    def hold(path: Path):
        yield path

    monkeypatch.setattr(store, "write_protected_file_replace", publish)
    monkeypatch.setattr(store, "hold_protected_file_for_read", hold)
    expected = store.RuntimeSettingsProjection(
        public_base_url="https://public.example",
        budget_advisor_owner_confirmed=True,
    )
    store.write_runtime_settings(target, expected, service_owned=True)

    assert publications == [(target, target.read_text(encoding="utf-8"), True)]
    assert target.read_bytes().endswith(b"\n")
    assert store.read_runtime_settings(target, service_owned=False) == expected

    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["unknown"] = "rejected"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="closed"):
        store.read_runtime_settings(target, service_owned=False)


def test_owner_console_runtime_settings_no_longer_mutate_lifecycle_env() -> None:
    source = (BACKEND / "app" / "services" / "runtime_settings_service.py").read_text(encoding="utf-8")

    assert "_ENV_PATH" not in source
    assert "Path.write_text" not in source
    assert "patch_runtime_settings" in source
    assert "os.environ" not in source


def test_runtime_settings_reader_preserves_lexical_reparse_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import runtime_settings_store as store

    target = tmp_path / "dangling-runtime-settings.json"
    observed: list[Path] = []

    @contextmanager
    def reject_reparse(path: Path):
        observed.append(path)
        raise OSError("reparse rejected")
        yield path

    monkeypatch.setattr(store.os.path, "lexists", lambda _path: True)
    monkeypatch.setattr(store, "hold_protected_file_for_read", reject_reparse)
    with pytest.raises(OSError, match="reparse rejected"):
        store.read_runtime_settings(target, service_owned=False)
    assert observed == [Path(os.path.abspath(target))]


def test_runtime_settings_patch_serializes_read_merge_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import runtime_settings_store as store

    target = (tmp_path / "runtime-settings.json").resolve()
    defaults = store.RuntimeSettingsProjection(
        public_base_url="",
        budget_advisor_owner_confirmed=False,
    )
    active = 0
    maximum_active = 0
    counter_lock = threading.Lock()
    start = threading.Barrier(3)

    def observed_read(_path: Path, *, service_owned: bool):
        nonlocal active, maximum_active
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        with counter_lock:
            active -= 1
        return defaults

    monkeypatch.setattr(store, "read_runtime_settings", observed_read)
    monkeypatch.setattr(store, "write_runtime_settings", lambda *args, **kwargs: None)

    def worker(mutation) -> None:
        start.wait()
        store.patch_runtime_settings(
            target,
            defaults=defaults,
            mutation=mutation,
            service_owned=False,
        )

    threads = (
        threading.Thread(
            target=worker,
            args=(store.RuntimeSettingsMutation("public_base_url", "https://one.example"),),
        ),
        threading.Thread(
            target=worker,
            args=(store.RuntimeSettingsMutation("budget_advisor_owner_confirmed", True),),
        ),
    )
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert maximum_active == 1


def test_settings_snapshot_prefers_closed_runtime_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import config
    from app.services.runtime_settings_store import (
        RuntimeSettingsProjection,
        write_runtime_settings,
    )

    target = (tmp_path / "runtime-settings.json").resolve()
    write_runtime_settings(
        target,
        RuntimeSettingsProjection(
            public_base_url="https://projection.example",
            budget_advisor_owner_confirmed=True,
        ),
        service_owned=False,
    )
    monkeypatch.setattr(config, "RUNTIME_SETTINGS_PATH", target)
    monkeypatch.setattr(config, "_RUNTIME_SETTINGS_SERVICE_OWNED", False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://environment.example")
    monkeypatch.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "false")
    monkeypatch.setenv("UPLOAD_DIR", str((tmp_path / "uploads").resolve()))
    config.reset_settings_cache()
    try:
        settings = config.get_settings()
        assert settings.public_base_url == "https://projection.example"
        assert settings.budget_advisor_owner_confirmed is True
    finally:
        config.reset_settings_cache()


def test_service_projection_authority_requires_owner_capable_service_sid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def service_sid(_advapi32: object, _kernel32: object, *, require_owner: bool) -> str:
        calls.append(require_owner)
        return "S-1-5-80-1-2-3-4-5"

    monkeypatch.setattr(secure_file, "_windows_apis", lambda: (object(), object()))
    monkeypatch.setattr(
        secure_file._windows_acl,
        "current_process_service_sid",
        service_sid,
    )
    owner, rules = secure_file._windows_service_projection_authority()

    assert calls == [True]
    assert owner == "S-1-5-80-1-2-3-4-5"
    assert rules[owner] == secure_file._FILE_ALL_ACCESS


def test_service_sid_owner_bit_uses_the_windows_literal_contract() -> None:
    selector = secure_file._windows_acl._select_dedicated_service_sid
    service_sid = "S-1-5-80-1-2-3-4-5"

    with pytest.raises(PermissionError):
        selector(((service_sid, 0x00000004),), require_owner=True)
    assert (
        selector(
            ((service_sid, 0x00000004 | 0x00000008),),
            require_owner=True,
        )
        == service_sid
    )


def test_windows_protected_replace_is_write_through_and_identity_preserving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (tmp_path / ".settings.staging").resolve()
    destination = (tmp_path / "settings.json").resolve()
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")
    moves: list[tuple[str, str, int]] = []

    @contextmanager
    def hold(
        path: Path,
        *,
        owner_sids: frozenset[str],
        access_rules: dict[str, int],
    ):
        assert owner_sids == frozenset({"S-1-5-80-1-2-3-4-5"})
        assert access_rules["S-1-5-80-1-2-3-4-5"] == secure_file._FILE_ALL_ACCESS
        yield SimpleNamespace(stat=lambda: SimpleNamespace(st_dev=7, st_ino=11))

    class Kernel:
        @staticmethod
        def MoveFileExW(old: str, new: str, flags: int) -> bool:  # noqa: N802
            moves.append((old, new, flags))
            return True

    monkeypatch.setattr(secure_file, "_hold_windows_protected_file", hold)
    monkeypatch.setattr(secure_file, "_windows_apis", lambda: (object(), Kernel()))
    secure_file._publish_windows_file_replace(
        source,
        destination,
        owner_sid="S-1-5-80-1-2-3-4-5",
        access_rules={"S-1-5-80-1-2-3-4-5": secure_file._FILE_ALL_ACCESS},
    )

    assert moves == [
        (
            str(source),
            str(destination),
            0x00000009,
        )
    ]


def test_windows_protected_replace_rejects_dangling_destination_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (tmp_path / ".settings.staging").resolve()
    destination = tmp_path / "dangling-settings.json"
    source.write_text("new", encoding="utf-8")
    held: list[Path] = []
    moves: list[tuple[str, str, int]] = []

    @contextmanager
    def hold(
        path: Path,
        *,
        owner_sids: frozenset[str],
        access_rules: dict[str, int],
    ):
        held.append(path)
        if path == destination:
            raise OSError("destination reparse rejected")
        yield SimpleNamespace(stat=lambda: SimpleNamespace(st_dev=7, st_ino=11))

    monkeypatch.setattr(secure_file, "_hold_windows_protected_file", hold)
    monkeypatch.setattr(secure_file.os.path, "lexists", lambda path: path == destination)
    monkeypatch.setattr(Path, "exists", lambda _path: False)

    class Kernel:
        @staticmethod
        def MoveFileExW(old: str, new: str, flags: int) -> bool:  # noqa: N802
            moves.append((old, new, flags))
            return True

    monkeypatch.setattr(secure_file, "_windows_apis", lambda: (object(), Kernel()))

    with pytest.raises(OSError, match="destination reparse rejected"):
        secure_file._publish_windows_file_replace(
            source,
            destination,
            owner_sid="S-1-5-80-1-2-3-4-5",
            access_rules={"S-1-5-80-1-2-3-4-5": secure_file._FILE_ALL_ACCESS},
        )

    assert held == [source, destination]
    assert moves == []
