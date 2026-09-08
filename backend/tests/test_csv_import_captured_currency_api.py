"""The durable import preview and every apply request share the file's money."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import CsvImportBatch, CsvImportRow, Expense


def test_mixed_currency_preview_paged_apply_and_replay_keep_each_rows_amount(client, web_client, identity):
    content = b"home_currency_code,amount_cents,merchant\nJPY,1200,Train\nCNY,1234,Cafe\n"
    response = client.post(
        "/api/imports/csv", headers=identity.app_headers,
        files={"csv_file": ("currencies.csv", content, "text/csv")},
    )
    assert response.status_code == 201, response.json()
    batch = response.json()
    assert (batch["valid_rows"], batch["error_rows"]) == (2, 0)
    endpoint = f"/api/imports/csv/{batch['public_id']}"
    rows = client.get(f"{endpoint}/rows", headers=identity.app_headers)
    assert rows.status_code == 200, rows.json()
    assert [(row["home_currency_code"], row["amount_cents"]) for row in rows.json()["items"]] == [
        ("JPY", 1200), ("CNY", 1234),
    ]
    page = web_client.get(f"/web/import/{batch['public_id']}?ledger_id=owner")
    assert page.status_code == 200
    assert "JPY ¥1,200" in page.text
    assert "CNY ¥12.34" in page.text
    for inserted, remaining in [(1, 1), (1, 0), (0, 0)]:
        applied = client.post(f"{endpoint}/apply", headers=identity.app_headers, json={"batch_size": 1})
        assert applied.status_code == 200, applied.json()
        assert (applied.json()["inserted_count"], applied.json()["remaining_valid_rows"]) == (inserted, remaining)
    with SessionLocal() as db:
        stored = db.scalar(select(CsvImportBatch).where(CsvImportBatch.public_id == batch["public_id"]))
        rows = db.scalars(select(CsvImportRow).where(CsvImportRow.batch_id == stored.id).order_by(CsvImportRow.line_number)).all()
        assert len(rows) == stored.inserted_count == 2
        assert len({row.expense_id for row in rows}) == 2
        for row, expected in zip(rows, [("JPY", 1200), ("CNY", 1234)], strict=True):
            expense = db.get(Expense, row.expense_id)
            assert row.status == "applied"
            assert (expense.home_currency_code, expense.amount_cents) == expected
            assert (expense.original_currency_code, expense.original_amount_minor) == expected


def test_foreign_import_resolves_the_rows_rate_pair_under_a_different_default(client, identity):
    for home, rate in [("CNY", "7"), ("JPY", "150")]:
        response = client.put(
            "/api/exchange-rates/USD/2026-09-08", headers=identity.app_headers,
            json={"home_currency_code": home, "currency_code": "USD", "rate_date": "2026-09-08",
                  "rate_to_cny": rate, "source": "manual"},
        )
        assert response.status_code == 200, response.json()
    content = (
        "home_currency_code,amount_cents,original_currency_code,original_amount_minor,exchange_rate_date,merchant\n"
        "JPY,,USD,100,2026-09-08,Foreign train\n"
    )
    created = client.post(
        "/api/imports/csv", headers=identity.app_headers,
        files={"csv_file": ("foreign.csv", content.encode(), "text/csv")},
    )
    assert created.status_code == 201, created.json()
    assert created.json()["valid_rows"] == 1, created.json()
    applied = client.post(f"/api/imports/csv/{created.json()['public_id']}/apply", headers=identity.app_headers)
    assert applied.status_code == 200, applied.json()
    assert applied.json()["inserted_count"] == 1
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.merchant == "Foreign train"))
        assert (expense.home_currency_code, expense.amount_cents) == ("JPY", 150)
        assert (expense.original_currency_code, expense.original_amount_minor) == ("USD", 100)
        assert expense.exchange_rate_to_cny == 150
