from __future__ import annotations

from pathlib import Path

from app.config import installation_identity


def test_installed_identity_uses_explicit_binding_not_data_path(monkeypatch, tmp_path: Path) -> None:
    install_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setenv("TICKETBOX_INSTALLATION_ID", install_id)

    assert installation_identity(tmp_path / "arbitrary-data-root") == install_id
