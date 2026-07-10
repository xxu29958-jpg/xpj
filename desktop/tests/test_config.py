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
from backend_manager.installation import InstalledLayout


def test_all_urls_derive_from_one_host_port_pair() -> None:
    cfg = ManagerConfig(
        runtime=SourceRuntimeConfig(backend_root=Path("x"), venv_python=Path("y")),
        backend_host="10.0.0.5",
        backend_port=9001,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url="https://t.example",
    )
    assert cfg.backend_origin == "http://10.0.0.5:9001"
    assert cfg.health_url == "http://10.0.0.5:9001/api/health"
    assert cfg.owner_url == "http://10.0.0.5:9001/owner"
    assert cfg.manager_url == "http://127.0.0.1:8799/"


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
    for host in ("0.0.0.0", "192.168.31.86", "::"):
        monkeypatch.setenv("TICKETBOX_MANAGER_HOST", host)
        with pytest.raises(ConfigError):
            load_config()


def test_loopback_manager_hosts_are_accepted(tmp_path: Path, monkeypatch) -> None:
    root = _fake_backend(tmp_path)
    monkeypatch.setenv("TICKETBOX_MANAGER_MODE", "source")
    monkeypatch.setenv("TICKETBOX_BACKEND_ROOT", str(root))
    for host in ("127.0.0.1", "127.0.0.5", "localhost", "::1"):
        monkeypatch.setenv("TICKETBOX_MANAGER_HOST", host)
        assert load_config().manager_host == host


def test_auto_mode_prefers_installed_layout_and_reads_program_data_env(tmp_path: Path, monkeypatch) -> None:
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
    )
    monkeypatch.setattr("backend_manager.config.discover_installed_layout", lambda: layout)
    monkeypatch.delenv("TICKETBOX_BACKEND_ROOT", raising=False)
    monkeypatch.delenv("TICKETBOX_MANAGER_MODE", raising=False)
    monkeypatch.setenv("TICKETBOX_BACKEND_HOST", "10.0.0.9")
    monkeypatch.setenv("TICKETBOX_BACKEND_PORT", "9999")

    cfg = load_config()

    assert isinstance(cfg.runtime, InstalledRuntimeConfig)
    assert cfg.runtime.layout == layout
    assert cfg.runtime.log_path == app_data / "logs" / "backend.log"
    assert cfg.backend_host == "127.0.0.1"
    assert cfg.backend_port == 8123
    assert cfg.public_base_url == "https://public.example"


def test_installed_mode_requires_installer_registry(monkeypatch) -> None:
    monkeypatch.setenv("TICKETBOX_MANAGER_MODE", "installed")
    monkeypatch.setattr("backend_manager.config.discover_installed_layout", lambda: None)

    with pytest.raises(ConfigError, match="未找到小票夹正式安装信息"):
        load_config()
