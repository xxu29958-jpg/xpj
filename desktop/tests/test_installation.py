"""Installed-instance binding and runtime-layout contracts."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from backend_manager import installation
from backend_manager.installation import (
    InstalledLayout,
    WindowsReleaseConfig,
    load_installed_release_config,
    parse_installed_binding,
)
from backend_manager.lifecycle_lock import hold_installer_lifecycle_lock
from backend_manager.windows_machine_state import _require_exact_binding_security

_INSTALL_ID = "11111111-1111-4111-8111-111111111111"


def _release_config() -> WindowsReleaseConfig:
    return WindowsReleaseConfig(
        backend_service_name="TicketboxBackendCustom",
        pg_service_name="TicketboxPgCustom",
        service_state_timeout_ms=17_000,
        service_poll_interval_ms=125,
        postgres_ready_timeout_ms=23_000,
        backend_ready_timeout_ms=31_000,
        backend_ready_poll_interval_ms=375,
        backend_health_request_timeout_ms=1_750,
    )


def test_legacy_registry_without_binding_is_not_an_installed_instance(monkeypatch) -> None:
    monkeypatch.setattr(installation, "_read_installation_binding", lambda: None)
    monkeypatch.setattr(
        installation,
        "_read_install_dir",
        lambda: (_ for _ in ()).throw(AssertionError("registry is not authority")),
    )
    assert installation.discover_installed_layout() is None


def test_installed_release_config_comes_only_from_binding_layout(tmp_path: Path) -> None:
    layout = InstalledLayout(
        install_dir=tmp_path / "program",
        data_root=tmp_path / "data",
        backend_port=8000,
        pg_port=5432,
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        backend_version="1.2.0",
        install_id=_INSTALL_ID,
        health_attestation_key="a" * 64,
    )
    retired_config = layout.install_dir / "installer" / "windows-release-config.json"
    retired_config.parent.mkdir(parents=True)
    retired_config.write_text('{"backend_service_name":"RetiredBackendOwner"}', encoding="utf-8")
    release = load_installed_release_config(layout)

    assert release.backend_service_name == "TicketboxBackend"
    assert release.pg_service_name == "TicketboxPg"
    assert release.backend_health_request_timeout_ms == 2_000


def test_parse_installed_binding_uses_installation_json_not_registry_dataroot(tmp_path: Path) -> None:
    layout = parse_installed_binding(
        {
            "schema": "ticketbox-installed-instance-v1",
            "install_id": "11111111-1111-4111-8111-111111111111",
            "data_root": str(tmp_path / "data"),
            "active_release_id": "1.2.0",
            "pg_service_name": "TicketboxPg",
            "backend_service_name": "TicketboxBackend",
            "pg_port": 5432,
            "backend_port": 8000,
            "health_attestation_key": "a" * 64,
        },
        str(tmp_path / "program"),
    )
    assert layout.data_root == (tmp_path / "data").resolve()
    assert layout.backend_version == "1.2.0"
    assert layout.installation_id == _INSTALL_ID
    release = load_installed_release_config(layout)
    assert release.backend_service_name == "TicketboxBackend"
    assert release.pg_service_name == "TicketboxPg"
    assert release.backend_health_request_timeout_ms == 2000


def test_discover_installed_layout_requires_binding_and_uses_registry_only_as_locator(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        installation,
        "_read_installation_binding",
        lambda: {
            "schema": "ticketbox-installed-instance-v1",
            "install_id": "11111111-1111-4111-8111-111111111111",
            "data_root": str(tmp_path / "bound-data"),
            "active_release_id": "1.2.0",
            "pg_service_name": "TicketboxPg",
            "backend_service_name": "TicketboxBackend",
            "pg_port": 5432,
            "backend_port": 8000,
            "health_attestation_key": "a" * 64,
        },
    )
    monkeypatch.setattr(
        installation,
        "_read_install_dir",
        lambda: str(tmp_path / "program"),
    )
    layout = installation.discover_installed_layout()
    assert layout is not None
    assert layout.install_dir == (tmp_path / "program").resolve()
    assert layout.data_root == (tmp_path / "bound-data").resolve()
    assert layout.backend_service_name == "TicketboxBackend"


def test_binding_path_ignores_poisoned_programdata_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted = tmp_path / "official-programdata"
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "attacker"))
    monkeypatch.setattr(installation, "machine_binding_path", lambda: trusted / "binding.json")

    assert installation._installation_binding_path() == trusted / "binding.json"


def test_binding_json_is_loaded_only_through_protected_retained_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        installation,
        "read_protected_binding_bytes",
        lambda: calls.append("protected-read") or b'{"schema":"ticketbox-installed-instance-v1"}',
    )

    assert installation._read_installation_binding() == {
        "schema": "ticketbox-installed-instance-v1"
    }
    assert calls == ["protected-read"]


@pytest.mark.parametrize(
    ("owner", "sddl"),
    [
        (
            "S-1-5-21-9-9-9-1002",
            "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;S-1-5-80-1-2-3-4-5)"
            "(A;;FR;;;S-1-5-21-9-9-9-1001)",
        ),
        (
            "S-1-5-32-544",
            "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;S-1-5-80-1-2-3-4-5)"
            "(A;;FR;;;S-1-5-21-9-9-9-1001)(A;;FR;;;WD)",
        ),
        (
            "S-1-5-32-544",
            "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;S-1-5-80-1-2-3-4-5)"
            "(A;;FR;;;S-1-5-21-9-9-9-1001)",
        ),
        (
            "S-1-5-32-544",
            "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;S-1-5-80-1-2-3-4-5)",
        ),
    ],
)
def test_binding_security_rejects_untrusted_owner_broad_or_inexact_acl(
    owner: str,
    sddl: str,
) -> None:
    with pytest.raises(RuntimeError):
        _require_exact_binding_security(
            owner,
            sddl,
            current_user_sid="S-1-5-21-9-9-9-1001",
            backend_service_sid="S-1-5-80-1-2-3-4-5",
        )


def test_binding_security_accepts_only_system_admin_backend_and_current_user() -> None:
    _require_exact_binding_security(
        "S-1-5-32-544",
        "D:PAI(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;S-1-5-80-1-2-3-4-5)"
        "(A;;FR;;;S-1-5-21-9-9-9-1001)",
        current_user_sid="S-1-5-21-9-9-9-1001",
        backend_service_sid="S-1-5-80-1-2-3-4-5",
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows file-share semantics required")
def test_python_lifecycle_lock_interoperates_with_real_powershell_hosts(tmp_path: Path) -> None:
    lock_path = tmp_path / "installer-lifecycle.lock"
    lock_script = Path(__file__).parents[2] / "backend" / "packaging" / "windows_lifecycle_lock.ps1"
    harness = tmp_path / "lock-interoperability.ps1"
    escaped_script = str(lock_script).replace("'", "''")
    escaped_lock = str(lock_path).replace("'", "''")
    harness.write_text(
        "#Requires -Version 5.1\n"
        f". '{escaped_script}'\n"
        f"$lock = Enter-TicketboxExclusiveFileLock '{escaped_lock}'\n"
        "try { exit 0 } finally { $lock.Dispose() }\n",
        encoding="utf-8-sig",
    )
    hosts = [Path(found) for name in ("powershell", "pwsh") if (found := shutil.which(name))]
    assert hosts, "no PowerShell host available"

    with hold_installer_lifecycle_lock(path=lock_path):
        blocked = [subprocess.run([host, "-NoProfile", "-File", harness], check=False).returncode for host in hosts]
    acquired = [subprocess.run([host, "-NoProfile", "-File", harness], check=False).returncode for host in hosts]

    assert blocked == [1] * len(hosts)
    assert acquired == [0] * len(hosts)
