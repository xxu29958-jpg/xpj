"""Bundled Manager UI asset boundary; live UI risks run in Edge."""

from __future__ import annotations

from pathlib import Path


def test_manager_package_ships_only_ui_html_without_product_assets() -> None:
    spec = (Path(__file__).parents[1] / "packaging" / "ticketbox-manager.spec").read_text(encoding="utf-8")

    assert '"ui.html"' in spec or "'ui.html'" in spec
    assert "product.html" not in spec
    assert "product.css" not in spec
    assert "product.js" not in spec
