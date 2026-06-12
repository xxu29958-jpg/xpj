"""ADR-0038 /web undo contract tests: reject → 5s banner → undo restores pending.

Covers the /web slice of the expense-undo three-tier(backend / web / Android):

- POST /web/expenses/{id}/reject redirects to /web/pending with msg + undo=<id> +
  flash_type=success;  /web/pending GET reads ``undo`` from the query, verifies
  the row is actually rejected AND owned by the current ledger, exposes it as
  ``undo_expense_id``, and pending.html renders a 5s 撤销 banner posting to
  /web/expenses/{id}/undo.
- POST /web/expenses/{id}/undo restores the row to pending and writes a
  ``ledger_audit_logs action='undo'`` row (same as the /api route).
- Past-window / wrong-status / cross-tenant / missing-row collapse to a flash
  message + ``flash_type=error`` so the page renders the red danger banner
  instead of the green success one (review P2 #1).
- /web/pending sanitises ``undo``: non-numeric values, expenses that don't belong
  to the current ledger, and rows not currently in rejected state all silently
  drop the banner (review P2 #3 — cross-ledger noise).
- pending.html injects ``csrf_token`` explicitly so the form survives even if
  csrf.js fails to load (belt-and-braces vs the import_export.html regression
  in #196). A lightweight assertion below pins this so a template-variable typo
  can't ship green.

Note: /web routes are LocalOnly OR session-gated. We use ``web_client`` which
bypasses the loopback gate (peer is 'testclient'). CSRF middleware is also
testclient-exempt (csrf.py:64-65) so the form posts here go through without
a token — the public-web CSRF lane is covered by test_public_web_security_layers.
"""
# coverage: cross-ledger
# coverage: existence-404

from __future__ import annotations

import re
from datetime import timedelta

from api_contract_helpers import web_reject_expense, web_undo_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerAuditLog
from app.services.soft_delete_policy import SOFT_DELETE_RETENTION
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES


def _create_pending(client: TestClient, *, identity) -> int:
    resp = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def test_web_reject_redirects_with_undo_query_and_success_flash(
    web_client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(web_client, identity=identity)

    response = web_reject_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    location = response.headers.get("location", "")
    assert "/web/pending" in location
    assert f"undo={expense_id}" in location
    assert "msg=" in location  # 已忽略这笔账单。 banner text
    assert "flash_type=success" in location  # review P2 #1: green banner


def test_web_pending_renders_undo_banner_in_green_when_success_flash(
    web_client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    web_reject_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )

    page = web_client.get(
        f"/web/pending?ledger_id=owner&undo={expense_id}&msg=已忽略这笔账单。&flash_type=success"
    )
    assert page.status_code == 200, page.text
    body = page.text
    assert f"/web/expenses/{expense_id}/undo" in body
    assert "undo-banner" in body
    assert "撤销" in body
    # review P2 #1: the success flash renders green, not red.
    assert "dt-alert success" in body
    assert "dt-alert danger" not in body


def test_web_pending_undo_form_carries_csrf_token(
    web_client: TestClient, *, identity
) -> None:
    # review P2 #2: belt-and-braces CSRF — pending.html injects ``csrf_token`` as
    # a hidden field so the form works even if csrf.js fails. testclient is
    # CSRF-exempt at the middleware so a typo like ``value="{{ wrong_var }}"``
    # would never trigger a 403 in unit tests. Pin the field's presence and a
    # non-empty value so a template regression can't ship green.
    expense_id = _create_pending(web_client, identity=identity)
    web_reject_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )
    page = web_client.get(
        f"/web/pending?ledger_id=owner&undo={expense_id}&msg=ok&flash_type=success"
    )
    assert page.status_code == 200, page.text
    # The form scope: extract csrf_token from the undo banner specifically (not
    # any other form on the page).
    banner_match = re.search(
        r'<form[^>]*action="/web/expenses/\d+/undo"[^>]*>(.+?)</form>',
        page.text,
        flags=re.DOTALL,
    )
    assert banner_match, "undo banner form must be rendered"
    token_match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"', banner_match.group(1)
    )
    assert token_match, "undo form must carry csrf_token field"
    assert token_match.group(1), "csrf_token value must be non-empty"


def test_web_pending_ignores_non_numeric_undo_value(
    web_client: TestClient, *, identity
) -> None:
    # Defensive sanitisation: a malformed redirect (e.g. ``undo=foo``) should not
    # render a broken form. The page still loads with the flash, just no banner.
    page = web_client.get("/web/pending?ledger_id=owner&undo=not-an-id&msg=ok")
    assert page.status_code == 200, page.text
    assert "undo-banner" not in page.text
    assert "/web/expenses/not-an-id/undo" not in page.text


def test_web_pending_drops_undo_for_cross_ledger_expense(
    web_client: TestClient, *, identity
) -> None:
    # review P2 #3: an ``?undo=<id>`` query against a row that doesn't belong to
    # the currently-selected ledger (or isn't currently rejected) must not render
    # the misleading "可撤销" banner. The route itself is the source of truth
    # via WHERE tenant_id + status, but the page also stops lying.
    expense_id = _create_pending(web_client, identity=identity)
    web_reject_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )

    create_ledger = web_client.post(
        "/api/ledgers",
        headers=identity.admin_headers,
        json={"name": "另一本"},
    )
    assert create_ledger.status_code == 201, create_ledger.text
    other_ledger_id = create_ledger.json()["ledger_id"]

    # Page rendered for the other ledger with a stale ``undo`` query: banner gone.
    page = web_client.get(
        f"/web/pending?ledger_id={other_ledger_id}&undo={expense_id}&msg=已忽略&flash_type=success"
    )
    assert page.status_code == 200, page.text
    assert "undo-banner" not in page.text
    assert f"/web/expenses/{expense_id}/undo" not in page.text


def test_web_pending_drops_undo_for_non_rejected_row(
    web_client: TestClient, *, identity
) -> None:
    # Ownership-check companion: even within the right ledger, a pending row must
    # not surface the undo banner. Either the row was never rejected, or someone
    # else / the same user from another tab already undid it.
    expense_id = _create_pending(web_client, identity=identity)
    page = web_client.get(
        f"/web/pending?ledger_id=owner&undo={expense_id}&msg=已忽略&flash_type=success"
    )
    assert page.status_code == 200, page.text
    assert "undo-banner" not in page.text
    assert f"/web/expenses/{expense_id}/undo" not in page.text


def test_web_undo_after_reject_restores_pending_and_writes_audit(
    web_client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    web_reject_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )

    response = web_undo_expense(web_client, expense_id, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = response.headers.get("location", "")
    assert "/web/pending" in location
    assert "msg=" in location  # 已撤销 banner text
    assert "flash_type=success" in location  # review P2 #1
    # Successful undo does NOT re-emit the undo query — no nested undo.
    assert "undo=" not in location

    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        assert row.status == "pending"
        assert row.rejected_at is None
        audit = db.scalar(
            select(LedgerAuditLog)
            .where(LedgerAuditLog.action == "undo")
            .where(LedgerAuditLog.resource_type == "expense")
            .where(LedgerAuditLog.resource_public_id == row.public_id)
        )
        assert audit is not None


def test_web_undo_after_window_expires_flashes_red_failure(
    web_client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    web_reject_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )

    # Hand-age rejected_at past the 5-min cutoff.
    aged = now_utc() - SOFT_DELETE_RETENTION - timedelta(seconds=10)
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        row.rejected_at = aged
        db.commit()

    response = web_undo_expense(web_client, expense_id, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = response.headers.get("location", "")
    assert "/web/pending" in location
    assert "msg=" in location  # 无法撤销 wording
    assert "flash_type=error" in location  # review P2 #1: failure → red banner

    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        assert row.status == "rejected"
        assert row.rejected_at is not None

    # Follow the redirect to confirm the rendered page uses the danger class,
    # not the success class.
    page = web_client.get(location)
    assert page.status_code == 200, page.text
    assert "dt-alert danger" in page.text
    assert "dt-alert success" not in page.text


def test_web_undo_for_pending_row_flashes_failure(
    web_client: TestClient, *, identity
) -> None:
    # Never rejected — undo has nothing to restore.
    expense_id = _create_pending(web_client, identity=identity)
    response = web_undo_expense(web_client, expense_id, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert "/web/pending" in response.headers.get("location", "")
    # Row remains pending; no audit written.
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        assert row.status == "pending"
        audit = db.scalar(
            select(LedgerAuditLog)
            .where(LedgerAuditLog.action == "undo")
            .where(LedgerAuditLog.resource_type == "expense")
        )
        assert audit is None


def test_web_undo_from_different_ledger_form_flashes_failure(
    web_client: TestClient, *, identity
) -> None:
    # Cross-ledger: reject in the default 'owner' ledger, then submit /undo
    # with form ledger_id pointing at a different (newly-created) ledger.
    # The atomic UPDATE WHERE tenant_id=<other_ledger> matches zero rows,
    # so the row stays rejected and no audit is written.
    expense_id = _create_pending(web_client, identity=identity)
    web_reject_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )

    create_ledger = web_client.post(
        "/api/ledgers",
        headers=identity.admin_headers,
        json={"name": "另一本"},
    )
    assert create_ledger.status_code == 201, create_ledger.text
    other_ledger_id = create_ledger.json()["ledger_id"]

    response = web_undo_expense(
        web_client,
        expense_id,
        ledger_id=other_ledger_id,
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text

    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        assert row.status == "rejected"
        assert row.rejected_at is not None
        audit = db.scalar(
            select(LedgerAuditLog)
            .where(LedgerAuditLog.action == "undo")
            .where(LedgerAuditLog.resource_type == "expense")
            .where(LedgerAuditLog.resource_public_id == row.public_id)
        )
        assert audit is None, "cross-ledger /web undo must not write a ledger_audit_logs row"
