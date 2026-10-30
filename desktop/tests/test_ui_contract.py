"""Bundled Manager UI asset boundary; live UI risks run in Edge."""

from __future__ import annotations

from pathlib import Path

from backend_manager.brand_icon import FAVICON_LINK
from backend_manager.control_server import _recovery_page


def test_manager_package_ships_only_ui_html_without_product_assets() -> None:
    spec = (Path(__file__).parents[1] / "packaging" / "ticketbox-manager.spec").read_text(encoding="utf-8")

    assert '"ui.html"' in spec or "'ui.html'" in spec
    assert "product.html" not in spec
    assert "product.css" not in spec
    assert "product.js" not in spec


def test_manager_pages_share_the_generated_ticketbox_icon() -> None:
    """ui.html and the server-written pages both come from render_icons.py; keep them identical."""
    ui = (Path(__file__).resolve().parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert ui.count('rel="icon"') == 1
    assert FAVICON_LINK in ui
    assert FAVICON_LINK.encode() in _recovery_page("小票夹服务尚未就绪")
