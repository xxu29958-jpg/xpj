"""Control-server authorization contract — the CSRF defenses, as a pure-function test."""

from __future__ import annotations

from backend_manager.control_server import is_authorized

_TOKEN = "s3cr3t-token"
_ORIGIN = "http://127.0.0.1:8799"


def _auth(**overrides: object) -> bool:
    kwargs: dict = {
        "token": _TOKEN,
        "provided_token": _TOKEN,
        "sec_fetch_site": "same-origin",
        "origin": _ORIGIN,
        "expected_origin": _ORIGIN,
    }
    kwargs.update(overrides)
    return is_authorized(**kwargs)  # type: ignore[arg-type]


def test_valid_token_same_origin_is_allowed() -> None:
    assert _auth() is True


def test_missing_token_is_rejected() -> None:
    assert _auth(provided_token=None) is False


def test_wrong_token_is_rejected() -> None:
    assert _auth(provided_token="nope") is False


def test_cross_site_fetch_is_rejected() -> None:
    # A malicious page's request carries Sec-Fetch-Site: cross-site.
    assert _auth(sec_fetch_site="cross-site") is False


def test_foreign_origin_is_rejected() -> None:
    assert _auth(origin="https://evil.example") is False


def test_token_alone_passes_when_fetch_metadata_absent() -> None:
    # Older clients / non-browser callers omit Sec-Fetch-Site and Origin; the
    # unguessable token still gates the request.
    assert _auth(sec_fetch_site=None, origin=None) is True
