from __future__ import annotations

import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path

import pytest


def _load_launch_module():
    launch_path = Path(__file__).resolve().parents[1] / "launch.py"
    spec = importlib.util.spec_from_file_location("ticketbox_guard_launch", launch_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _authority(launch, tmp_path: Path, data_dir: Path):
    return launch._installer_guard.InstalledRuntimeAuthority(
        runtime_junction=data_dir.parent,
        install_dir=(tmp_path / "install").resolve(),
        data_root=(tmp_path / "data").resolve(),
    )


@contextmanager
def _hold(path: Path):
    yield path


def test_valid_installer_guard_initializes_settings_before_app_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    data_dir = (tmp_path / "runtime-binding" / "app").resolve()
    settings_dir = data_dir / "runtime-settings"
    settings_dir.mkdir(parents=True)
    authority = _authority(launch, tmp_path, data_dir)
    guard = (tmp_path / "installer-runtime-recovery-pending").resolve()
    guard.write_text(
        json.dumps(
            {
                "schema": "ticketbox-installer-runtime-recovery-guard-v1",
                "state": "installer_transaction_pending",
                "install_dir": str(authority.install_dir),
                "data_root": str(authority.data_root),
                "created_at_utc": "2026-08-22T01:02:03+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH", str(guard))
    monkeypatch.setattr(
        launch._installer_guard,
        "hold_system_runtime_projection_for_read",
        _hold,
    )

    from app.services import runtime_settings_store as store

    publications = []

    def initialize(path, projection, *, service_owned):
        publications.append((path, projection, service_owned))
        return projection

    monkeypatch.setattr(store, "initialize_runtime_settings", initialize)
    launch._initialize_installed_runtime_settings(data_dir, authority)

    assert publications == [
        (
            settings_dir / "runtime-settings.json",
            store.RuntimeSettingsProjection(
                public_base_url="",
                budget_advisor_owner_confirmed=False,
            ),
            True,
        )
    ]
    source = (Path(__file__).resolve().parents[1] / "launch.py").read_text(
        encoding="utf-8"
    )
    assert source.index(
        "_initialize_installed_runtime_settings(data_dir, validated_runtime_junction)"
    ) < source.index("from app.main import app as fastapi_app")

    guard.unlink()
    launch._initialize_installed_runtime_settings(data_dir, authority)
    assert len(publications) == 1


def test_malformed_installer_guard_cannot_authorize_settings_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    data_dir = (tmp_path / "runtime-binding" / "app").resolve()
    guard = (tmp_path / "installer-runtime-recovery-pending").resolve()
    guard.write_text("pending", encoding="utf-8")
    monkeypatch.setenv("TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH", str(guard))
    monkeypatch.setattr(
        launch._installer_guard,
        "hold_system_runtime_projection_for_read",
        _hold,
    )
    from app.services import runtime_settings_store as store

    publications = []
    monkeypatch.setattr(
        store,
        "initialize_runtime_settings",
        lambda *args, **kwargs: publications.append((args, kwargs)),
    )
    with pytest.raises(RuntimeError, match="installer runtime recovery guard"):
        launch._initialize_installed_runtime_settings(
            data_dir,
            _authority(launch, tmp_path, data_dir),
        )
    assert publications == []


@pytest.mark.parametrize(
    "guard_failure",
    (
        PermissionError("guard ACL rejected"),
        OSError("guard reparse rejected"),
        ValueError("guard is not a regular file"),
    ),
)
def test_unprotected_installer_guard_cannot_authorize_settings_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    guard_failure: BaseException,
) -> None:
    launch = _load_launch_module()
    data_dir = (tmp_path / "runtime-binding" / "app").resolve()
    guard = (tmp_path / "installer-runtime-recovery-pending").resolve()
    guard.write_text("present", encoding="utf-8")
    monkeypatch.setenv("TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH", str(guard))

    @contextmanager
    def reject(_path: Path):
        raise guard_failure
        yield

    monkeypatch.setattr(
        launch._installer_guard,
        "hold_system_runtime_projection_for_read",
        reject,
    )
    from app.services import runtime_settings_store as store

    publications = []
    monkeypatch.setattr(
        store,
        "initialize_runtime_settings",
        lambda *args, **kwargs: publications.append((args, kwargs)),
    )
    with pytest.raises(RuntimeError, match="guard is not protected"):
        launch._initialize_installed_runtime_settings(
            data_dir,
            _authority(launch, tmp_path, data_dir),
        )
    assert publications == []
