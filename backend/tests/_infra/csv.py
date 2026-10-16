"""Use the saved-import parser for existing CSV row and round-trip checks."""

from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Expense, ExpenseOffsetFact, ExpenseOffsetRevision, ExpenseRevision
from app.services.csv_import_batch_service._lifecycle import _csv_import_limits, _parse_csv_import_rows
from tests._web_native_form_support import hidden_post_forms
from tests.expense_correction_support import _create_refund, _foreign_expense, _seed_usd_rate, idem


def parse_uploaded_csv(content: str, timezone_name: str | None = None, *, home_currency: str):
    max_bytes, max_cell_bytes, max_data_rows, _ = _csv_import_limits()
    rows, _, valid_count, error_count = _parse_csv_import_rows(
        BytesIO(content.encode("utf-8")),
        max_bytes=max_bytes,
        max_cell_bytes=max_cell_bytes,
        max_data_rows=max_data_rows,
        timezone_name=timezone_name or get_settings().ocr_default_timezone,
        home_currency=home_currency,
        calendar_revision=1,
    )
    return SimpleNamespace(rows=rows, valid_count=valid_count, error_count=error_count)


def _batch(client, headers, content: bytes) -> str:
    response = client.post(
        "/api/imports/csv", headers=headers,
        files={"csv_file": ("ticketbox-events.csv", content, "text/csv")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["error_rows"] == 0, response.json()
    return response.json()["public_id"]


def _rows(client, headers, batch: str, *, status: str | None = None) -> dict:
    response = client.get(
        f"/api/imports/csv/{batch}/rows", headers=headers,
        params={"status": status} if status else None,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _apply(client, headers, batch: str, *, size: int = 10) -> dict:
    response = client.post(
        f"/api/imports/csv/{batch}/apply", headers=headers, json={"batch_size": size},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _export(client, headers, **filters) -> bytes:
    response = client.get("/api/expenses/export.csv", headers=headers, params=filters)
    assert response.status_code == 200, response.text
    assert "text/csv" in response.headers["content-type"]
    return response.content


def _bundle(client, headers, expense_id: int) -> dict:
    response = client.get(f"/api/expenses/{expense_id}/fact-bundle", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _fact_counts(ledger_id: str) -> tuple[int, ...]:
    with SessionLocal() as db:
        return tuple(
            db.scalar(select(func.count()).select_from(model).where(model.tenant_id == ledger_id))
            for model in (Expense, ExpenseOffsetFact, ExpenseRevision, ExpenseOffsetRevision)
        )


def _foreign_source_export(client, identity) -> tuple[bytes, dict]:
    _seed_usd_rate(client, identity, "2026-05-04", "7")
    _seed_usd_rate(client, identity, "2026-05-05", "8")
    expense = _foreign_expense(client, identity, "原币退货订单")
    created = _create_refund(client, identity, expense)
    offset, = created["active_offsets"]
    corrected = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "original_amount_minor": 2500, "accounting_date": "2026-05-05",
            "category": "售后", "offset_reason": "部分商品退货", "correction_reason": "独立归类退款",
            "expected_row_version": offset["row_version"],
        },
    )
    assert corrected.status_code == 201, corrected.text
    return _export(client, identity.app_headers), corrected.json()


def _csv_bytes(row_count: int) -> BytesIO:
    lines = ["amount_yuan,merchant,category,note"]
    lines.extend(f"{index}.00,Merchant {index},餐饮,note {index}" for index in range(1, row_count + 1))
    return BytesIO(("\n".join(lines) + "\n").encode("utf-8"))


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


def _import_foreign_bill(client: TestClient, identity) -> dict:
    content = (
        "home_currency_code,amount_cents,original_currency_code,original_amount_minor,expense_time,merchant,category\n"
        "CNY,,USD,12345,2026-05-03T16:30:00Z,Historical foreign receipt,交通\n"
    )
    created = client.post(
        "/api/imports/csv", headers=identity.app_headers,
        files={"csv_file": ("foreign.csv", content.encode(), "text/csv")},
    )
    assert created.status_code == 201, created.text
    batch = created.json()
    assert (batch["valid_rows"], batch["error_rows"]) == (1, 0)
    endpoint = f"/api/imports/csv/{batch['public_id']}"
    applied = client.post(f"{endpoint}/apply", headers=identity.app_headers, json={"batch_size": 1})
    assert applied.status_code == 200, applied.text
    assert applied.json()["inserted_count"] == 1
    rows = client.get(f"{endpoint}/rows", headers=identity.app_headers)
    assert rows.status_code == 200, rows.text
    row = rows.json()["items"][0]
    assert row["status"] == "applied"
    detail = client.get(f"/api/expenses/{row['expense_id']}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.text
    bill = detail.json()
    assert bill["status"] == "pending"
    assert (bill["home_currency"], bill["original_currency_code"], bill["original_amount_minor"]) == (
        "CNY", "USD", 12345,
    )
    assert bill["expense_time"] == "2026-05-03T16:30:00Z"
    assert bill["category"] == "交通"
    assert bill["accounting_time"]["user_local_date"] == "2026-05-03"
    assert bill["accounting_time"]["accounting_date"] == "2026-05-04"
    return bill
