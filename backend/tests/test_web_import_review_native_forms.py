"""Rendered import/review forms must work without client-side token injection."""

import re
from datetime import timedelta
from html import unescape
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from _web_native_form_support import hidden_post_forms
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import CsvImportBatch, Expense, LedgerMember
from app.services.csv_import_batch_service import _claim_apply_lease
from app.services.time_service import now_utc


def test_native_csv_preview_and_apply_preserve_selected_ledger(web_client, identity) -> None:
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 53007)) as browser:
        page = browser.get("/web/import?ledger_id=tester_1")
        assert page.status_code == 200
        preview_action = "/web/import/preview"
        preview = browser.post(
            preview_action,
            data=hidden_post_forms(page.text)[preview_action],
            files={"csv_file": ("review.csv", "amount_yuan,merchant,category\n18.50,早餐咖啡,餐饮\n待补,午餐小馆,餐饮\n".encode(), "text/csv")},
            headers={"Origin": "http://127.0.0.1", "Referer": str(page.url)},
            follow_redirects=False,
        )
        assert preview.status_code == 303, preview.text
        detail = browser.get(preview.headers["location"])
        assert detail.status_code == 200
        public_id = detail.url.path.rsplit("/", 1)[-1]
        before = browser.get(f"/api/imports/csv/{public_id}", headers=identity.gray_app_headers)
        assert before.status_code == 200
        assert before.json()["applied_rows"] == 0
        assert before.json()["valid_rows"] == 1
        assert before.json()["error_rows"] == 1

        action = f"/web/import/{public_id}/apply"
        applied = browser.post(
            action,
            data={**hidden_post_forms(detail.text)[action], "batch_size": "1"},
            headers={"Origin": "http://127.0.0.1", "Referer": str(detail.url)},
            follow_redirects=False,
        )
        assert applied.status_code == 303, applied.text
        selected = browser.get("/api/expenses/pending", headers=identity.gray_app_headers)
        assert selected.status_code == 200
        assert len(selected.json()) == 1
        row = selected.json()[0]
        assert row["amount_cents"] == 1850
        assert row["merchant"] == "早餐咖啡"
        assert row["status"] == "pending"
        default = browser.get("/api/expenses/pending", headers=identity.app_headers)
        assert default.status_code == 200
        assert default.json() == []
        repeated = browser.post(
            action,
            data={**hidden_post_forms(detail.text)[action], "batch_size": "1"},
            headers={"Origin": "http://127.0.0.1", "Referer": str(detail.url)},
            follow_redirects=False,
        )
        assert repeated.status_code == 303
        after = browser.get(f"/api/imports/csv/{public_id}", headers=identity.gray_app_headers)
        assert after.json()["applied_rows"] == 1


def test_native_uncategorized_updates_only_selected_pending_row(web_client, identity) -> None:
    created = []
    for merchant in ("清晨咖啡", "街角午餐"):
        response = web_client.post(
            "/api/expenses/notification-drafts", headers=identity.gray_app_headers,
            json={"source": "alipay", "amount_cents": 1850, "merchant": merchant, "category": "其他"},
        )
        assert response.status_code == 200, response.text
        created.append(response.json()["id"])
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 53008)) as browser:
        page = browser.get("/web/categories/uncategorized?ledger_id=tester_1")
        assert page.status_code == 200
        action = "/web/categories/uncategorized/bulk-set"
        changed = browser.post(
            action,
            data={**hidden_post_forms(page.text)[action], "expense_ids": str(created[0]), "category": "餐饮"},
            headers={"Origin": "http://127.0.0.1", "Referer": str(page.url)},
            follow_redirects=False,
        )
        assert changed.status_code == 303, changed.text
        for expense_id, category in zip(created, ("餐饮", "其他"), strict=True):
            response = browser.get(f"/api/expenses/{expense_id}", headers=identity.gray_app_headers)
            assert response.status_code == 200
            assert response.json()["category"] == category
            assert response.json()["status"] == "pending"
        outside_scope = browser.get(f"/api/expenses/{created[0]}", headers=identity.app_headers)
        assert outside_scope.status_code == 404


def _preview_native_csv(browser, *, ledger_id, csv_text, file_name="saved.csv") -> tuple[str, str]:
    page = browser.get("/web/import", params={"ledger_id": ledger_id})
    assert page.status_code == 200, page.text
    action = "/web/import/preview"
    response = browser.post(
        action,
        data=hidden_post_forms(page.text)[action],
        files={"csv_file": (file_name, csv_text.encode(), "text/csv")},
        headers={"Origin": str(browser.base_url).rstrip("/"), "Referer": str(page.url)},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    target = urlsplit(response.headers["location"])
    assert target.path.startswith("/web/import/")
    assert parse_qs(target.query)["ledger_id"] == [ledger_id]
    return target.path.rsplit("/", 1)[-1], response.headers["location"]


def _apply_native_csv(browser, *, public_id, ledger_id, batch_size=1):
    page = browser.get(f"/web/import/{public_id}", params={"ledger_id": ledger_id})
    assert page.status_code == 200, page.text
    action = f"/web/import/{public_id}/apply"
    response = browser.post(
        action,
        data={**hidden_post_forms(page.text)[action], "batch_size": str(batch_size)},
        headers={"Origin": str(browser.base_url).rstrip("/"), "Referer": str(page.url)},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response


def _batch_href(html: str, public_id: str, ledger_id: str) -> str:
    matches = [
        unescape(href) for href in re.findall(r'href="([^"]+)"', html)
        if urlsplit(unescape(href)).path == f"/web/import/{public_id}"
    ]
    assert matches, f"The import hub must expose the original batch {public_id}"
    assert all(parse_qs(urlsplit(href).query).get("ledger_id") == [ledger_id] for href in matches)
    return matches[0]


def _batch_next_actions(html: str) -> str:
    matched = re.search(r'<section\b[^>]*aria-label="下一步"[^>]*>(.*?)</section>', html, re.DOTALL)
    assert matched is not None
    return matched.group(1)


def test_native_csv_returns_to_original_partial_batch_without_duplicate_rows(web_client, identity) -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "tester_1").limit(1))
        assert member is not None
        member.role = "member"
        db.commit()
    csv_text = "amount_yuan,merchant,category\n18.50,First original row,餐饮\n9.00,Second original row,交通\n"
    public_id, detail_url = _preview_native_csv(web_client, ledger_id="tester_1", csv_text=csv_text)
    _apply_native_csv(web_client, public_id=public_id, ledger_id="tester_1")
    before = web_client.get("/api/expenses/pending", headers=identity.gray_app_headers)
    assert before.status_code == 200 and len(before.json()) == 1
    first_id = before.json()[0]["id"]

    # No remembered detail URL: leave for another workspace, then use the normal import entry.
    assert web_client.get("/web/pending?ledger_id=tester_1").status_code == 200
    hub = web_client.get("/web/import?ledger_id=tester_1")
    assert hub.status_code == 200
    resumed = web_client.get(_batch_href(hub.text, public_id, "tester_1"))
    assert resumed.status_code == 200
    assert urlsplit(str(resumed.url)).path == urlsplit(detail_url).path
    _apply_native_csv(web_client, public_id=public_id, ledger_id="tester_1")

    after = web_client.get("/api/expenses/pending", headers=identity.gray_app_headers)
    assert after.status_code == 200
    assert {row["merchant"]: (row["amount_cents"], row["status"]) for row in after.json()} == {
        "First original row": (1850, "pending"), "Second original row": (900, "pending"),
    }
    assert len(after.json()) == 2 and first_id in {row["id"] for row in after.json()}
    with SessionLocal() as db:
        keys = list(db.scalars(select(Expense.draft_idempotency_key).where(Expense.tenant_id == "tester_1")))
    assert set(keys) == {f"csv-import:{public_id}:2", f"csv-import:{public_id}:3"}
    completed = web_client.get(detail_url)
    assert f"/web/import/{public_id}/apply" not in hidden_post_forms(completed.text)

    # Selecting the same source file again creates a separate receipt, never a continuation alias.
    reuploaded_id, _ = _preview_native_csv(web_client, ledger_id="tester_1", csv_text=csv_text)
    assert reuploaded_id != public_id
    new_batch = web_client.get(f"/api/imports/csv/{reuploaded_id}", headers=identity.gray_app_headers)
    old_batch = web_client.get(f"/api/imports/csv/{public_id}", headers=identity.gray_app_headers)
    assert new_batch.json()["applied_rows"] == 0 and old_batch.json()["applied_rows"] == 2
    assert len(web_client.get("/api/expenses/pending", headers=identity.gray_app_headers).json()) == 2


def test_native_csv_hub_is_scoped_and_viewer_can_only_inspect(web_client, identity) -> None:
    outside_id, _ = _preview_native_csv(
        web_client, ledger_id="owner", csv_text="amount_yuan,merchant\n1.00,Outside ledger\n",
        file_name="outside-ledger.csv",
    )
    public_id, detail_url = _preview_native_csv(
        web_client, ledger_id="tester_1", csv_text="amount_yuan,merchant\n2.00,Selected ledger\n",
        file_name="selected-ledger.csv",
    )
    before = web_client.get(detail_url)
    action = f"/web/import/{public_id}/apply"
    original_form = hidden_post_forms(before.text)[action]
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "tester_1").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()

    hub = web_client.get("/web/import?ledger_id=tester_1")
    assert hub.status_code == 200
    _batch_href(hub.text, public_id, "tester_1")
    assert outside_id not in hub.text and "outside-ledger.csv" not in hub.text
    assert "/web/import/preview" not in hidden_post_forms(hub.text)
    detail = web_client.get(detail_url)
    assert detail.status_code == 200 and action not in hidden_post_forms(detail.text)
    assert web_client.get(f"/web/import/{public_id}/errors.csv?ledger_id=tester_1").status_code == 200
    denied = web_client.post(
        action, data=original_form,
        headers={"Origin": str(web_client.base_url).rstrip("/"), "Referer": str(detail.url)},
        follow_redirects=False,
    )
    assert denied.status_code == 403, denied.text
    assert web_client.get("/api/expenses/pending", headers=identity.gray_app_headers).json() == []
    outside = web_client.get(f"/web/import/{outside_id}?ledger_id=tester_1", follow_redirects=False)
    assert outside.status_code == 303
    assert urlsplit(outside.headers["location"]).path == "/web/import"


def test_native_csv_active_lease_refusal_keeps_original_batch_for_later_apply(web_client, identity) -> None:
    public_id, _ = _preview_native_csv(
        web_client, ledger_id="owner", csv_text="amount_yuan,merchant\n3.00,Held first\n4.00,Held second\n",
    )
    with SessionLocal() as db:
        _claim_apply_lease(db, tenant_id="owner", public_id=public_id, apply_token=str(uuid4()))
    refused = _apply_native_csv(web_client, public_id=public_id, ledger_id="owner")
    target = urlsplit(refused.headers["location"])
    assert target.path == f"/web/import/{public_id}"
    assert parse_qs(target.query)["ledger_id"] == ["owner"]
    assert "稍后重试" in parse_qs(target.query)["msg"][0]
    assert web_client.get("/api/expenses/pending", headers=identity.app_headers).json() == []

    # Only the existing lease time changes; read/return navigation must not release ownership.
    with SessionLocal() as db:
        batch = db.scalar(select(CsvImportBatch).where(CsvImportBatch.public_id == public_id))
        assert batch is not None and batch.locked_until is not None and batch.apply_token is not None
        batch.locked_until = now_utc() - timedelta(seconds=1)
        db.commit()
    _apply_native_csv(web_client, public_id=public_id, ledger_id="owner", batch_size=2)
    pending = web_client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200 and len(pending.json()) == 2


def test_native_csv_partial_insert_failure_offers_error_receipt_not_another_apply(
    web_client, identity, monkeypatch,
) -> None:
    from app.errors import AppError
    from app.services.csv_import_batch_service import _apply

    process_row = _apply._process_csv_import_apply_row

    def fail_second_row(db, **kwargs):
        if kwargs["row"].merchant == "Rejected original row":
            raise AppError("invalid_request", "This original row could not be imported.", status_code=422)
        return process_row(db, **kwargs)

    monkeypatch.setattr(_apply, "_process_csv_import_apply_row", fail_second_row)
    public_id, detail_url = _preview_native_csv(
        web_client, ledger_id="owner",
        csv_text="amount_yuan,merchant\n5.00,Applied original row\n6.00,Rejected original row\n",
    )
    _apply_native_csv(web_client, public_id=public_id, ledger_id="owner", batch_size=2)
    batch = web_client.get(f"/api/imports/csv/{public_id}", headers=identity.app_headers).json()
    assert (batch["valid_rows"], batch["applied_rows"], batch["error_rows"]) == (2, 1, 1)
    assert batch["status"] == "applied_with_errors"
    hub = web_client.get("/web/import?ledger_id=owner")
    _batch_href(hub.text, public_id, "owner")
    detail = web_client.get(detail_url)
    assert f"/web/import/{public_id}/apply" not in hidden_post_forms(detail.text)
    assert "本批次的可导入行已全部进入" not in detail.text
    errors = web_client.get(f"/web/import/{public_id}/errors.csv?ledger_id=owner")
    assert errors.status_code == 200 and "Rejected original row" in errors.text
    assert "Applied original row" not in errors.text
    pending = web_client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200 and len(pending.json()) == 1


@pytest.mark.parametrize("older_amount", ["8.00", "invalid"], ids=["unfinished", "all-invalid"])
def test_native_csv_older_batch_remains_reachable_through_hub_pagination(web_client, older_amount) -> None:
    older_id, _ = _preview_native_csv(
        web_client, ledger_id="owner", csv_text=f"amount_yuan,merchant\n{older_amount},Original older row\n",
        file_name="older.csv",
    )
    newer_id, _ = _preview_native_csv(
        web_client, ledger_id="owner", csv_text="amount_yuan,merchant\n7.00,Newer valid row\n",
        file_name="newer.csv",
    )
    first = web_client.get("/web/import?ledger_id=owner&page=1&page_size=1")
    assert first.status_code == 200
    _batch_href(first.text, newer_id, "owner")
    assert older_id not in first.text
    next_links = [
        unescape(href) for href in re.findall(r'href="([^"]+)"', first.text)
        if urlsplit(unescape(href)).path == "/web/import"
        and parse_qs(urlsplit(unescape(href)).query).get("page") == ["2"]
    ]
    assert next_links, "Older saved batches must remain reachable beyond the first page"
    query = parse_qs(urlsplit(next_links[0]).query)
    assert query["ledger_id"] == ["owner"] and query["page_size"] == ["1"]
    second = web_client.get(next_links[0])
    detail = web_client.get(_batch_href(second.text, older_id, "owner"))
    assert detail.status_code == 200
    assert (f"/web/import/{older_id}/apply" in hidden_post_forms(detail.text)) == (older_amount != "invalid")
    if older_amount == "invalid":
        assert 'href="/web/pending?ledger_id=owner"' not in _batch_next_actions(detail.text)
        assert f'href="/web/import/{older_id}/errors.csv?ledger_id=owner"' in detail.text
        errors = web_client.get(f"/web/import/{older_id}/errors.csv?ledger_id=owner")
        assert errors.status_code == 200 and "Original older row" in errors.text
