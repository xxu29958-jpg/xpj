"""Desktop shell browser and Edge app-window behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_manager import desktop_shell


def test_edge_discovery_prefers_dynamic_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    edge = tmp_path / "msedge.exe"
    edge.write_bytes(b"test")
    monkeypatch.setattr(desktop_shell.shutil, "which", lambda _name: str(edge))

    assert desktop_shell.discover_edge_executable() == str(edge)


def test_app_window_falls_back_to_default_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(desktop_shell, "discover_edge_executable", lambda: None)
    monkeypatch.setattr(desktop_shell, "open_in_browser", opened.append)

    desktop_shell.open_app_window("http://127.0.0.1:8799/")

    assert opened == ["http://127.0.0.1:8799/"]
