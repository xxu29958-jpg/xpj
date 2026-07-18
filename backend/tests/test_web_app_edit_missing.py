"""Missing-expense regressions for the /web expense editor and sub-forms."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_web_edit_missing_expense_redirects_with_flash(web_client: TestClient) -> None:
    """A stale link / cross-ledger expense id must not render a bare-JSON
    page; the full-page form redirects back to the confirmed list."""
    resp = web_client.get(
        "/web/expenses/999999/edit?ledger_id=owner", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/confirmed")


def test_web_edit_missing_expense_fragment_returns_readable_html(
    web_client: TestClient,
) -> None:
    """The drawer fetch (desktop.js does not check res.ok) must receive a
    readable HTML snippet, not raw JSON injected into the drawer."""
    resp = web_client.get(
        "/web/expenses/999999/edit?ledger_id=owner&fragment=1",
        follow_redirects=False,
    )
    assert resp.status_code == 404
    assert "没有找到这笔账单" in resp.text
    assert not resp.text.lstrip().startswith("{")


def test_web_save_missing_expense_redirects_with_flash(web_client: TestClient) -> None:
    """Audit P2 #6: the save error path re-reads the expense to re-render the
    form; for a vanished row that second read used to escape to the global
    bare-JSON handler. It must flash-redirect like the GET guard instead."""
    resp = web_client.post(
        "/web/expenses/999999/save",
        data={"amount_yuan": "1.00", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner", "expected_row_version": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/confirmed")
    assert "msg=" in resp.headers["location"]
    assert not resp.text.lstrip().startswith("{")


def test_web_confirm_missing_expense_redirects_with_flash(web_client: TestClient) -> None:
    resp = web_client.post(
        "/web/expenses/999999/confirm",
        data={"ledger_id": "owner", "expected_row_version": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/pending")
    assert "msg=" in resp.headers["location"]


def test_web_confirm_stale_token_on_missing_expense_redirects_with_flash(
    web_client: TestClient,
) -> None:
    """The parsed-None branch (stale form on a deleted row) shares the guard."""
    resp = web_client.post(
        "/web/expenses/999999/confirm",
        data={"ledger_id": "owner", "expected_row_version": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/pending")


def test_web_reject_missing_expense_redirects_with_flash(web_client: TestClient) -> None:
    resp = web_client.post(
        "/web/expenses/999999/reject",
        data={"ledger_id": "owner", "expected_row_version": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/pending")
    assert "msg=" in resp.headers["location"]


def test_web_items_save_missing_expense_redirects_with_flash(web_client: TestClient) -> None:
    """codex follow-up on audit P2 #6: the items sub-form's error path re-reads
    the same expense — for a vanished row it used to escape as bare JSON."""
    resp = web_client.post(
        "/web/expenses/999999/items/save",
        data={"ledger_id": "owner", "expected_row_version": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/confirmed")
    assert "msg=" in resp.headers["location"]
    assert not resp.text.lstrip().startswith("{")


def test_web_items_acknowledge_missing_expense_redirects_with_flash(
    web_client: TestClient,
) -> None:
    resp = web_client.post(
        "/web/expenses/999999/items/acknowledge-mismatch",
        data={"ledger_id": "owner", "expected_row_version": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/confirmed")
    assert "msg=" in resp.headers["location"]


def test_web_items_acknowledge_stale_token_on_missing_expense_redirects(
    web_client: TestClient,
) -> None:
    """The parsed-None branch (stale form on a deleted row) shares the guard."""
    resp = web_client.post(
        "/web/expenses/999999/items/acknowledge-mismatch",
        data={"ledger_id": "owner", "expected_row_version": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/confirmed")


def test_web_splits_save_missing_expense_redirects_with_flash(web_client: TestClient) -> None:
    resp = web_client.post(
        "/web/expenses/999999/splits/save",
        data={"ledger_id": "owner", "expected_row_version": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/confirmed")
    assert "msg=" in resp.headers["location"]
