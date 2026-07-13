from __future__ import annotations

import importlib.util
import json
import ntpath
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

_RUNTIME_VOLUME_IDENTITY = "\\\\?\\Volume{11111111-2222-3333-4444-555555555555}\\"
_OTHER_VOLUME_IDENTITY = "\\\\?\\Volume{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}\\"


def _load_launch_module():
    launch_path = Path(__file__).resolve().parents[1] / "packaging" / "launch.py"
    spec = importlib.util.spec_from_file_location("ticketbox_authority_launch", launch_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_runtime_data_root_marker(
    runtime_root: Path,
    *,
    data_root: Path,
    install_dir: Path,
    volume_identity: str = _RUNTIME_VOLUME_IDENTITY,
) -> Path:
    runtime_root.mkdir(parents=True, exist_ok=True)
    marker_path = runtime_root / ".ticketbox-data-root.json"
    marker_path.write_text(
        json.dumps(
            {
                "schema": "ticketbox-data-root-v2",
                "data_root": str(data_root),
                "install_dir": str(install_dir),
                "data_volume_identity": volume_identity,
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    return marker_path


def _volume_bound_path(path: Path, volume_identity: str) -> str:
    _drive, tail = ntpath.splitdrive(str(path.resolve()))
    return volume_identity.upper() + tail.lstrip("\\")


def _configure_installed_runtime(monkeypatch, launch, tmp_path):
    runtime_root = tmp_path / "runtime-binding"
    data_root = tmp_path / "authoritative-data"
    install_dir = tmp_path / "install"
    executable = install_dir / "program" / "ticketbox-backend" / "ticketbox-backend.exe"
    executable.parent.mkdir(parents=True)
    data_root.mkdir()
    marker_path = _write_runtime_data_root_marker(
        runtime_root,
        data_root=data_root,
        install_dir=install_dir,
    )
    monkeypatch.setenv("TICKETBOX_DATA_DIR", str(runtime_root / "app"))
    monkeypatch.setenv(
        "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH",
        str(runtime_root / "bootstrap-exposure-recovery-pending"),
    )
    monkeypatch.setenv(
        "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH", str(tmp_path / "installer-guard")
    )
    monkeypatch.setenv("TICKETBOX_DATA_ROOT_MARKER_PATH", str(marker_path))
    monkeypatch.setenv("TICKETBOX_DATA_VOLUME_IDENTITY", _RUNTIME_VOLUME_IDENTITY)
    monkeypatch.setattr(launch, "_assert_runtime_marker_no_follow", lambda _path: None)
    monkeypatch.setattr(
        launch,
        "_windows_final_volume_path",
        lambda _path: _volume_bound_path(data_root, _RUNTIME_VOLUME_IDENTITY),
    )
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launch.sys, "executable", str(executable))
    return runtime_root, data_root, install_dir, marker_path


def test_source_runtime_does_not_require_installer_volume_authority(
    monkeypatch, tmp_path
):
    launch = _load_launch_module()
    preset = tmp_path / "source-data"
    monkeypatch.setenv("TICKETBOX_DATA_DIR", str(preset))
    monkeypatch.delenv("TICKETBOX_DATA_ROOT_MARKER_PATH", raising=False)
    monkeypatch.delenv("TICKETBOX_DATA_VOLUME_IDENTITY", raising=False)

    assert launch.configure_environment() == Path(os.path.abspath(preset))
    assert (preset / "uploads").is_dir()


def test_frozen_runtime_requires_complete_host_authority_before_write(
    monkeypatch, tmp_path
):
    launch = _load_launch_module()
    values = {
        "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH": str(tmp_path / "bootstrap-guard"),
        "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH": str(tmp_path / "installer-guard"),
        "TICKETBOX_DATA_ROOT_MARKER_PATH": str(tmp_path / "data-root-marker"),
        "TICKETBOX_DATA_VOLUME_IDENTITY": _RUNTIME_VOLUME_IDENTITY,
    }
    missing_cases = [tuple(values), *((key,) for key in values)]
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)

    for index, missing_keys in enumerate(missing_cases):
        preset = tmp_path / f"frozen-case-{index}" / "app"
        monkeypatch.setenv("TICKETBOX_DATA_DIR", str(preset))
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        for key in missing_keys:
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(RuntimeError, match="frozen backend host authority is incomplete") as error:
            launch.configure_environment()

        for key in missing_keys:
            assert key in str(error.value)
        assert not (preset / "uploads").exists()


@pytest.mark.parametrize(
    ("present_key", "missing_key"),
    [
        ("TICKETBOX_DATA_ROOT_MARKER_PATH", "TICKETBOX_DATA_VOLUME_IDENTITY"),
        ("TICKETBOX_DATA_VOLUME_IDENTITY", "TICKETBOX_DATA_ROOT_MARKER_PATH"),
    ],
)
def test_partial_runtime_authority_fails_before_write(
    monkeypatch, tmp_path, present_key, missing_key
):
    launch = _load_launch_module()
    runtime_root = tmp_path / "runtime-binding"
    preset = runtime_root / "app"
    values = {
        "TICKETBOX_DATA_ROOT_MARKER_PATH": str(
            runtime_root / ".ticketbox-data-root.json"
        ),
        "TICKETBOX_DATA_VOLUME_IDENTITY": _RUNTIME_VOLUME_IDENTITY,
    }
    monkeypatch.setenv("TICKETBOX_DATA_DIR", str(preset))
    monkeypatch.setenv(present_key, values[present_key])
    monkeypatch.delenv(missing_key, raising=False)

    with pytest.raises(RuntimeError, match="authority is incomplete"):
        launch.configure_environment()

    assert not (preset / "uploads").exists()


def test_volume_bound_runtime_authority_allows_writes(monkeypatch, tmp_path):
    launch = _load_launch_module()
    runtime_root, _data_root, _install_dir, _marker_path = _configure_installed_runtime(
        monkeypatch,
        launch,
        tmp_path,
    )
    preset = runtime_root / "app"

    assert launch.configure_environment() == Path(os.path.abspath(preset))
    assert (preset / "uploads").is_dir()


def test_bootstrap_guard_must_share_runtime_projection_before_write(
    monkeypatch, tmp_path
):
    launch = _load_launch_module()
    runtime_root, _data_root, _install_dir, _marker_path = _configure_installed_runtime(
        monkeypatch,
        launch,
        tmp_path,
    )
    preset = runtime_root / "app"
    monkeypatch.setenv(
        "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH",
        str(tmp_path / "drive-letter-reused" / "bootstrap-exposure-recovery-pending"),
    )

    with pytest.raises(RuntimeError, match="not bound to the runtime DataRoot projection"):
        launch.configure_environment()

    assert not (preset / "uploads").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows Volume GUID contract")
def test_windows_volume_identity_follows_runtime_junction(monkeypatch, tmp_path):
    launch = _load_launch_module()
    target = tmp_path / "target"
    junction = tmp_path / "runtime-data-root"
    target.mkdir()
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    try:
        assert launch._windows_final_volume_identity(
            junction
        ) == launch._windows_final_volume_identity(target)
        guard = junction / "bootstrap-exposure-recovery-pending"
        monkeypatch.setenv("TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH", str(guard))

        assert (
            launch._host_guard_is_present_or_malformed(
                guard,
                allowed_reparse_ancestor=junction,
            )
            is False
        )
        assert launch._host_guard_is_present_or_malformed(guard) is True
        launch._assert_bootstrap_recovery_not_pending(junction)
    finally:
        os.rmdir(junction)
    assert target.is_dir()


@pytest.mark.parametrize(
    ("marker_volume", "resolved_volume", "delete_marker", "message"),
    [
        (
            _OTHER_VOLUME_IDENTITY,
            _RUNTIME_VOLUME_IDENTITY,
            False,
            "marker Volume GUID does not match",
        ),
        (
            _RUNTIME_VOLUME_IDENTITY,
            _OTHER_VOLUME_IDENTITY,
            False,
            "junction resolved to another volume",
        ),
        (
            _RUNTIME_VOLUME_IDENTITY,
            _RUNTIME_VOLUME_IDENTITY,
            True,
            "marker is unavailable",
        ),
    ],
)
def test_broken_runtime_authority_fails_before_write(
    monkeypatch,
    tmp_path,
    marker_volume,
    resolved_volume,
    delete_marker,
    message,
):
    launch = _load_launch_module()
    runtime_root, data_root, install_dir, marker_path = _configure_installed_runtime(
        monkeypatch,
        launch,
        tmp_path,
    )
    preset = runtime_root / "app"
    marker_path = _write_runtime_data_root_marker(
        runtime_root,
        data_root=data_root,
        install_dir=install_dir,
        volume_identity=marker_volume,
    )
    if delete_marker:
        marker_path.unlink()
    monkeypatch.setattr(
        launch,
        "_windows_final_volume_path",
        lambda _path: _volume_bound_path(data_root, resolved_volume),
    )

    with pytest.raises(RuntimeError, match=message):
        launch.configure_environment()

    assert not (preset / "uploads").exists()


@pytest.mark.parametrize("mismatch", ["data_root", "install_dir"])
def test_marker_path_binding_mismatch_fails_before_write(monkeypatch, tmp_path, mismatch):
    launch = _load_launch_module()
    runtime_root, data_root, install_dir, marker_path = _configure_installed_runtime(
        monkeypatch,
        launch,
        tmp_path,
    )
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker[mismatch] = str(tmp_path / f"wrong-{mismatch}")
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    message = (
        "junction does not match the marker data_root"
        if mismatch == "data_root"
        else "marker does not match the frozen install directory"
    )
    with pytest.raises(RuntimeError, match=message):
        launch.configure_environment()

    assert not (runtime_root / "app" / "uploads").exists()


def test_runtime_marker_reparse_is_rejected_before_read():
    launch = _load_launch_module()

    class ReparseMarker:
        def lstat(self):
            return SimpleNamespace(
                st_mode=stat.S_IFLNK,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )

    with pytest.raises(RuntimeError, match="regular non-reparse file"):
        launch._assert_runtime_marker_no_follow(ReparseMarker())


def test_dotenv_cannot_replace_host_runtime_authority(monkeypatch, tmp_path):
    launch = _load_launch_module()
    runtime_root, _data_root, _install_dir, marker_path = _configure_installed_runtime(
        monkeypatch,
        launch,
        tmp_path,
    )
    preset = runtime_root / "app"
    preset.mkdir(parents=True)
    installer_guard = tmp_path / "trusted-installer-guard"
    bootstrap_guard = runtime_root / "bootstrap-exposure-recovery-pending"
    monkeypatch.setenv("TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH", str(installer_guard))
    monkeypatch.setenv("TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH", str(bootstrap_guard))
    (preset / ".env").write_text(
        "TICKETBOX_DATA_DIR=C:\\attacker-data\n"
        "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH=\n"
        "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH=C:\\attacker-guard\n"
        "TICKETBOX_DATA_ROOT_MARKER_PATH=C:\\attacker-marker\n"
        "TICKETBOX_DATA_VOLUME_IDENTITY=\\\\?\\Volume{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}\\\n",
        encoding="utf-8",
    )

    returned = launch.configure_environment()

    assert returned == preset.resolve()
    assert os.environ["TICKETBOX_DATA_DIR"] == str(preset.resolve())
    assert os.environ["TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH"] == str(installer_guard)
    assert os.environ["TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH"] == str(bootstrap_guard)
    assert os.environ["TICKETBOX_DATA_ROOT_MARKER_PATH"] == str(marker_path)
    assert os.environ["TICKETBOX_DATA_VOLUME_IDENTITY"] == _RUNTIME_VOLUME_IDENTITY
