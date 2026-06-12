"""批10: /web 待确认复核流 — drawer fetch-mutation contract + return_to whitelist.

The pending drawer's save / 确认 / 忽略草稿 (and the duplicate 标为非重复 button)
gained two opt-in Form params:

- ``fragment=1`` switches the response to the drawer fetch-mutation contract:
  success → a tiny ``data-drawer-ok`` 200 marker (never bare JSON, so desktop
  drawer.js — which doesn't check ``res.ok`` on the GET path — can swap it safely
  and remove the row / re-fetch), error → the drawer fragment re-rendered with
  the inline error so the reviewer keeps their place. A vanished row degrades to
  the readable empty-cell snippet at the row's status (mirrors the GET fragment
  guard), not bare JSON.
- ``return_to`` (save only, whitelisted) sends a *no-JS* save back to the queue
  instead of bouncing into the full edit page (the old 303 that popped the
  reviewer out of the list). An unknown value falls back to the route default —
  never widening the same-site redirect surface.

These exercise the route-layer behaviour; the JS pipeline (J/K, Ctrl+Enter,
auto-advance, shift-range select) has no test harness and is verified by hand.

CSRF middleware is testclient-exempt (csrf.py), and ``web_client`` bypasses the
loopback gate — so these posts go through without a token, same as the sibling
/web route tests.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests._infra.assets import PNG_BYTES


def _create_pending(client: TestClient, *, identity) -> int:
    resp = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _fresh_token(client: TestClient, expense_id: int, *, identity) -> str:
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert snapshot.status_code == 200, snapshot.text
    return str(snapshot.json()["row_version"])


# ── return_to whitelist (no-JS save path) ───────────────────────────────────


def test_web_save_return_to_pending_redirects_to_queue(
    web_client: TestClient, *, identity
) -> None:
    """A drawer save (no-JS path) carries hidden return_to=pending so it lands
    back on the queue instead of bouncing to the full edit page (the old 303
    that popped the reviewer out of the list)."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "amount_yuan": "5.00", "merchant": "店", "category": "餐饮", "note": "",
            "ledger_id": "owner", "expected_row_version": _fresh_token(
                web_client, expense_id, identity=identity
            ),
            "return_to": "pending",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/pending")


def test_web_save_return_to_unknown_falls_back_to_edit_page(
    web_client: TestClient, *, identity
) -> None:
    """An unrecognised return_to value is ignored — the success redirect falls
    back to the route default (full edit page), never widening the same-site
    redirect surface."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "amount_yuan": "5.00", "merchant": "店", "category": "餐饮", "note": "",
            "ledger_id": "owner", "expected_row_version": _fresh_token(
                web_client, expense_id, identity=identity
            ),
            "return_to": "https://evil.example.com/phish",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith(f"/web/expenses/{expense_id}/edit")
    assert "evil.example.com" not in resp.headers["location"]


def test_web_save_blank_return_to_uses_edit_page_default(
    web_client: TestClient, *, identity
) -> None:
    """Blank return_to keeps the legacy default (full edit page) for the
    direct-link save path."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "amount_yuan": "5.00", "merchant": "店", "category": "餐饮", "note": "",
            "ledger_id": "owner", "expected_row_version": _fresh_token(
                web_client, expense_id, identity=identity
            ),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith(f"/web/expenses/{expense_id}/edit")


# ── save fetch-mutation (fragment=1) ────────────────────────────────────────


def test_web_save_fragment_success_returns_marker_not_redirect(
    web_client: TestClient, *, identity
) -> None:
    """A successful drawer fetch-save returns a tiny 200 marker (not a redirect,
    never bare JSON); the client then re-fetches the row fragment."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "amount_yuan": "5.00", "merchant": "店", "category": "餐饮", "note": "",
            "ledger_id": "owner", "expected_row_version": _fresh_token(
                web_client, expense_id, identity=identity
            ),
            "fragment": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    assert 'data-drawer-ok="save"' in resp.text
    assert not resp.text.lstrip().startswith("{")
    payload = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    ).json()
    assert payload["amount_cents"] == 500


def test_web_save_fragment_error_returns_drawer_with_inline_error(
    web_client: TestClient, *, identity
) -> None:
    """A failed drawer fetch-save returns the drawer fragment carrying the inline
    error (so the reviewer keeps their place), not bare JSON. The status is
    non-2xx (422) so drawer.js — which keys off ``res.ok`` — swaps the error
    fragment in instead of treating the failure as success."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "amount_yuan": "not-a-number", "merchant": "", "category": "", "note": "",
            "ledger_id": "owner", "expected_row_version": _fresh_token(
                web_client, expense_id, identity=identity
            ),
            "fragment": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422, resp.text
    assert "请填写正确的金额" in resp.text
    assert "data-drawer-error" in resp.text  # drawer fragment, not the full page
    assert "data-drawer-form" in resp.text
    assert not resp.text.lstrip().startswith("{")


def test_web_save_fragment_missing_expense_returns_readable_html(
    web_client: TestClient,
) -> None:
    """A fetch-save on a vanished row degrades to the readable empty-cell snippet
    at the row's status (mirrors the GET fragment guard), not bare JSON injected
    into the drawer."""
    resp = web_client.post(
        "/web/expenses/999999/save",
        data={"amount_yuan": "1.00", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner", "expected_row_version": "1", "fragment": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 404, resp.text
    assert "empty-cell" in resp.text
    assert not resp.text.lstrip().startswith("{")


# ── confirm fetch-mutation (fragment=1) ─────────────────────────────────────


def test_web_confirm_fragment_success_returns_marker(
    web_client: TestClient, *, identity
) -> None:
    """A fetch-confirm success returns the 200 marker so the client removes the
    row + opens the next drawer."""
    expense_id = _create_pending(web_client, identity=identity)
    # Confirm needs an amount; save one first.
    web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "9.00", "merchant": "店", "category": "餐饮", "note": "",
              "ledger_id": "owner", "expected_row_version": _fresh_token(
                  web_client, expense_id, identity=identity
              )},
    )
    resp = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={"ledger_id": "owner", "expected_row_version": _fresh_token(
            web_client, expense_id, identity=identity
        ), "fragment": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    assert 'data-drawer-ok="confirm"' in resp.text
    payload = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    ).json()
    assert payload["status"] == "confirmed"


def test_web_confirm_fragment_error_returns_drawer_with_error(
    web_client: TestClient, *, identity
) -> None:
    """A fetch-confirm that fails business validation (no amount) swaps the drawer
    fragment back with the inline error rather than redirecting — at a non-2xx
    (422) status so the client doesn't mistake the failure for success and remove
    the row."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={"ledger_id": "owner", "expected_row_version": _fresh_token(
            web_client, expense_id, identity=identity
        ), "fragment": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 422, resp.text
    assert "请先填写金额" in resp.text
    assert "data-drawer-error" in resp.text
    assert not resp.text.lstrip().startswith("{")


def test_web_confirm_fragment_missing_expense_returns_readable_html(
    web_client: TestClient,
) -> None:
    resp = web_client.post(
        "/web/expenses/999999/confirm",
        data={"ledger_id": "owner", "expected_row_version": "1", "fragment": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 404, resp.text
    assert "empty-cell" in resp.text
    assert not resp.text.lstrip().startswith("{")


# ── reject fetch-mutation (fragment=1) ──────────────────────────────────────


def test_web_reject_fragment_success_returns_marker(
    web_client: TestClient, *, identity
) -> None:
    """A fetch-reject success returns the 200 marker (client removes the row +
    advances). The no-JS path keeps its 撤销 banner — covered separately in
    test_web_expense_undo."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/reject",
        data={"ledger_id": "owner", "expected_row_version": _fresh_token(
            web_client, expense_id, identity=identity
        ), "fragment": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    assert 'data-drawer-ok="reject"' in resp.text
    payload = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    ).json()
    assert payload["status"] == "rejected"


def test_web_reject_fragment_missing_expense_returns_readable_html(
    web_client: TestClient,
) -> None:
    resp = web_client.post(
        "/web/expenses/999999/reject",
        data={"ledger_id": "owner", "expected_row_version": "1", "fragment": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 404, resp.text
    assert "empty-cell" in resp.text
    assert not resp.text.lstrip().startswith("{")


# ── drawer fragment markup ──────────────────────────────────────────────────


def test_web_drawer_fragment_renders_return_to_pending_hidden(
    web_client: TestClient, *, identity
) -> None:
    """The drawer fragment carries hidden return_to=pending so a no-JS save lands
    back on the queue. The full edit page must NOT (its save returns to the edit
    page by design)."""
    expense_id = _create_pending(web_client, identity=identity)
    drawer = web_client.get(
        f"/web/expenses/{expense_id}/edit?ledger_id=owner&fragment=1"
    )
    assert drawer.status_code == 200
    assert 'name="return_to"' in drawer.text
    assert 'value="pending"' in drawer.text

    full = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert full.status_code == 200
    assert 'name="return_to"' not in full.text
