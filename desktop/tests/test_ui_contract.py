"""Security-sensitive static contracts for the localhost manager UI."""

from __future__ import annotations

from pathlib import Path


def test_backend_log_is_rendered_as_text_not_html() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert "row.textContent=line" in html
    assert "log.replaceChildren" in html
    assert "log.innerHTML" not in html


def test_narrow_window_switches_status_cards_to_vertical_layout() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert "@media (max-width:700px)" in html
    assert ".row{flex-direction:column;}" in html


def test_status_refresh_is_single_flight() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert "if(refreshInFlight) return" in html
    assert "finally{ refreshInFlight = false; }" in html
