from __future__ import annotations

from app.version import BACKEND_VERSION
from app.version import _resolve_static_asset_version


def test_static_asset_version_is_derived_from_asset_content(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("XPJ_STATIC_ASSET_VERSION", raising=False)
    backend_root = tmp_path / "backend"
    static_dir = backend_root / "app" / "static" / "web"
    template_dir = backend_root / "app" / "templates" / "web"
    static_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    style_path = static_dir / "shell.css"
    style_path.write_text(".shell { display: grid; }\n", encoding="utf-8")
    (template_dir / "base.html").write_text("<link rel='stylesheet'>\n", encoding="utf-8")

    first_version = _resolve_static_asset_version(backend_root)
    version_suffix = first_version.removeprefix(f"{BACKEND_VERSION}-")

    assert first_version.startswith(f"{BACKEND_VERSION}-")
    assert len(version_suffix) == 12
    int(version_suffix, 16)

    style_path.write_text(".shell { display: flex; }\n", encoding="utf-8")

    assert _resolve_static_asset_version(backend_root) != first_version


def test_static_asset_version_allows_release_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XPJ_STATIC_ASSET_VERSION", "release-asset-42")

    assert _resolve_static_asset_version(tmp_path) == "release-asset-42"
