"""ManagerConfig resolution — read from env + backend .env + discovery, nothing hardcoded."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_manager.config import (
    ConfigError,
    InstalledRuntimeConfig,
    ManagerConfig,
    SourceRuntimeConfig,
    load_config,
)
from backend_manager.installation import InstalledLayout, WindowsReleaseConfig, installation_id_for_app_data


def _release_config() -> WindowsReleaseConfig:
    return WindowsReleaseConfig(
        backend_service_name="TicketboxBackendConfigured",
        pg_service_name="TicketboxPgConfigured",
        service_state_timeout_ms=17_000,
        service_poll_interval_ms=125,
        postgres_ready_timeout_ms=23_000,
        backend_ready_timeout_ms=31_000,
        backend_ready_poll_interval_ms=375,
        backend_health_request_timeout_ms=1_750,
        database_tool_timeout_ms=600_000,
        dataset_backup_helper_timeout_ms=1_800_000,
        dataset_restore_helper_timeout_ms=3_600_000,
        dataset_payload_verification_timeout_ms=1_800_000,
        complete_dataset_backup_timeout_ms=5_400_000,
        complete_dataset_restore_timeout_ms=10_800_000,
    )


def test_all_urls_derive_from_one_host_port_pair() -> None:
    cfg = ManagerConfig(
        runtime=SourceRuntimeConfig(
            backend_root=Path("x"),
            venv_python=Path("y"),
            data_root=Path("x"),
        ),
        backend_host="0.0.0.0",
        backend_port=9001,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url="https://t.example",
        expected_backend_version=None,
        expected_installation_id="ticketbox-0123456789abcdef0123456789abcdef",
        health_request_timeout_seconds=3.0,
    )
    assert cfg.backend_origin == "http://127.0.0.1:9001"
    assert cfg.health_url == "http://127.0.0.1:9001/api/health/installation"
    assert cfg.owner_url == "http://127.0.0.1:9001/owner"
    assert cfg.manager_url == "http://127.0.0.1:8799/"
    assert cfg.manager_url_for_port(49152) == "http://127.0.0.1:49152/"


@pytest.mark.parametrize(
    ("host", "detected", "expected"),
    [
        ("127.0.0.1", "192.168.1.8", None),
        ("localhost", "192.168.1.8", None),
        ("0.0.0.0", "192.168.1.8", "192.168.1.8:9001"),
    ],
)
def test_lan_endpoint_matches_backend_bind_semantics(host: str, detected: str, expected: str | None) -> None:
    cfg = ManagerConfig(
        runtime=SourceRuntimeConfig(
            backend_root=Path("x"),
            venv_python=Path("y"),
            data_root=Path("x"),
        ),
        backend_host=host,
        backend_port=9001,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
        expected_backend_version=None,
        expected_installation_id="ticketbox-0123456789abcdef0123456789abcdef",
        health_request_timeout_seconds=3.0,
    )

    assert cfg.lan_endpoint(detected) == expected
    if host == "0.0.0.0":
        assert cfg.backend_origin == "http://127.0.0.1:9001"


def _fake_backend(tmp_path: Path, env_text: str = "PUBLIC_BASE_URL=https://api.example\n") -> Path:
    root = tmp_path / "backend"
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "python.exe").write_text("")
    (root / ".env").write_text(env_text, encoding="utf-8")
    return root


def test_load_config_reads_env_overrides_and_backend_dotenv(tmp_path: Path, monkeypatch) -> None:
    root = _fake_backend(tmp_path)
    monkeypatch.setenv("TICKETBOX_MANAGER_MODE", "source")
    monkeypatch.setenv("TICKETBOX_BACKEND_ROOT", str(root))
    monkeypatch.setenv("TICKETBOX_BACKEND_PORT", "9100")
    monkeypatch.delenv("TICKETBOX_BACKEND_HOST", raising=False)

    cfg = load_config()

    assert isinstance(cfg.runtime, SourceRuntimeConfig)
    assert cfg.runtime.backend_root == root.resolve()
    assert cfg.backend_port == 9100  # env override wins
    assert cfg.backend_host == "127.0.0.1"  # documented default
    assert cfg.public_base_url == "https://api.example"  # read from backend .env
    assert cfg.runtime.venv_python == root.resolve() / ".venv" / "Scripts" / "python.exe"
    assert cfg.runtime.data_root == root.resolve()


def test_source_relative_data_root_is_anchored_to_backend_root(tmp_path: Path, monkeypatch) -> None:
    root = _fake_backend(tmp_path)
    runtime_data = root / "runtime-data"
    runtime_data.mkdir()
    (runtime_data / ".env").write_text(
        "PUBLIC_BASE_URL=https://runtime.example\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETBOX_MANAGER_MODE", "source")
    monkeypatch.setenv("TICKETBOX_BACKEND_ROOT", str(root))
    monkeypatch.setenv("TICKETBOX_DATA_DIR", "runtime-data")
    monkeypatch.chdir(tmp_path.parent)

    cfg = load_config()

    assert isinstance(cfg.runtime, SourceRuntimeConfig)
    assert cfg.runtime.data_root == runtime_data.resolve()
    assert cfg.runtime.env_path == runtime_data.resolve() / ".env"
    assert cfg.public_base_url == "https://runtime.example"
    assert cfg.expected_installation_id == installation_id_for_app_data(cfg.runtime.data_root)


def test_missing_venv_interpreter_raises(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "backend"
    root.mkdir()
    (root / ".env").write_text("", encoding="utf-8")
    monkeypatch.setenv("TICKETBOX_MANAGER_MODE", "source")
    monkeypatch.setenv("TICKETBOX_BACKEND_ROOT", str(root))
    with pytest.raises(ConfigError):
        load_config()


def test_invalid_port_raises(tmp_path: Path, monkeypatch) -> None:
    root = _fake_backend(tmp_path)
    monkeypatch.setenv("TICKETBOX_MANAGER_MODE", "source")
    monkeypatch.setenv("TICKETBOX_BACKEND_ROOT", str(root))
    monkeypatch.setenv("TICKETBOX_BACKEND_PORT", "not-a-port")
    with pytest.raises(ConfigError):
        load_config()


def test_non_loopback_manager_host_raises(tmp_path: Path, monkeypatch) -> None:
    # The control surface serves a token + accepts control POSTs, so a public /
    # LAN bind is a security hole — load_config must refuse it before startup.
    root = _fake_backend(tmp_path)
    monkeypatch.setenv("TICKETBOX_MANAGER_MODE", "source")
    monkeypatch.setenv("TICKETBOX_BACKEND_ROOT", str(root))
    for host in ("0.0.0.0", "192.168.31.86", "::", "127.evil.test"):
        monkeypatch.setenv("TICKETBOX_MANAGER_HOST", host)
        with pytest.raises(ConfigError):
            load_config()


def test_supported_manager_hosts_are_accepted(tmp_path: Path, monkeypatch) -> None:
    root = _fake_backend(tmp_path)
    monkeypatch.setenv("TICKETBOX_MANAGER_MODE", "source")
    monkeypatch.setenv("TICKETBOX_BACKEND_ROOT", str(root))
    for host, expected in (
        ("127.0.0.1", "127.0.0.1"),
        ("127.0.0.5", "127.0.0.5"),
        ("localhost", "localhost"),
        ("  LOCALHOST  ", "localhost"),
    ):
        monkeypatch.setenv("TICKETBOX_MANAGER_HOST", host)
        assert load_config().manager_host == expected


@pytest.mark.parametrize("host", ["10.0.0.5", "::", "::1", "127.0.0.5", "127.evil.test"])
def test_source_backend_requires_ipv4_loopback_or_wildcard(
    tmp_path: Path,
    monkeypatch,
    host: str,
) -> None:
    root = _fake_backend(tmp_path)
    monkeypatch.setenv("TICKETBOX_MANAGER_MODE", "source")
    monkeypatch.setenv("TICKETBOX_BACKEND_ROOT", str(root))
    monkeypatch.setenv("TICKETBOX_BACKEND_HOST", host)

    with pytest.raises(ConfigError, match="127.0.0.1, localhost, or 0.0.0.0"):
        load_config()


def test_auto_mode_uses_safe_install_metadata_without_reading_protected_env(tmp_path: Path, monkeypatch) -> None:
    stale_source_root = _fake_backend(tmp_path)
    install_dir = tmp_path / "program"
    app_data = tmp_path / "data" / "app"
    install_dir.mkdir()
    app_data.mkdir(parents=True)
    (app_data / ".env").write_text("PUBLIC_BASE_URL=https://public.example\n", encoding="utf-8")
    layout = InstalledLayout(
        install_dir=install_dir,
        data_root=tmp_path / "data",
        backend_port=8123,
        pg_port=5544,
        backend_service_name="TicketboxBackendConfigured",
        pg_service_name="TicketboxPgConfigured",
        backend_version="9.8.7",
    )
    monkeypatch.setattr("backend_manager.config.discover_installed_layout", lambda: layout)
    monkeypatch.setattr("backend_manager.config.load_installed_release_config", lambda _layout: _release_config())
    monkeypatch.setattr(
        "backend_manager.config.dotenv_values",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("installed GUI read protected .env")),
    )
    monkeypatch.setenv("TICKETBOX_BACKEND_ROOT", str(stale_source_root))
    monkeypatch.delenv("TICKETBOX_MANAGER_MODE", raising=False)
    monkeypatch.setenv("TICKETBOX_BACKEND_HOST", "10.0.0.9")
    monkeypatch.setenv("TICKETBOX_BACKEND_PORT", "9999")

    cfg = load_config()

    assert isinstance(cfg.runtime, InstalledRuntimeConfig)
    assert cfg.runtime.layout == layout
    assert cfg.backend_host == "127.0.0.1"
    assert cfg.backend_port == 8123
    assert cfg.runtime.backend_service_name == "TicketboxBackendConfigured"
    assert cfg.runtime.pg_service_name == "TicketboxPgConfigured"
    assert cfg.public_base_url is None
    assert cfg.public_endpoint_state == "protected_unknown"
    assert cfg.expected_backend_version == "9.8.7"
    assert cfg.expected_installation_id == layout.installation_id
    assert cfg.health_request_timeout_seconds == 1.75
    assert cfg.runtime.release.service_state_timeout_seconds == 17


def test_auto_mode_falls_back_to_source_when_installation_is_absent(tmp_path: Path, monkeypatch) -> None:
    source_root = _fake_backend(tmp_path)
    monkeypatch.setenv("TICKETBOX_BACKEND_ROOT", str(source_root))
    monkeypatch.delenv("TICKETBOX_MANAGER_MODE", raising=False)
    monkeypatch.setattr("backend_manager.config.discover_installed_layout", lambda: None)

    cfg = load_config()

    assert isinstance(cfg.runtime, SourceRuntimeConfig)
    assert cfg.runtime.backend_root == source_root.resolve()


def test_installed_mode_requires_installer_registry(monkeypatch) -> None:
    monkeypatch.setenv("TICKETBOX_MANAGER_MODE", "installed")
    monkeypatch.setattr("backend_manager.config.discover_installed_layout", lambda: None)

    with pytest.raises(ConfigError, match="未找到小票夹正式安装信息"):
        load_config()
