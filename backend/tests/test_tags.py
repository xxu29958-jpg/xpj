from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Expense, ExpenseTag, Tag
from app.services.import_service import import_rows, parse_csv_preview


def _manual(
    client: TestClient,
    *,
    headers: dict[str, str],
    amount_cents: int,
    merchant: str,
    tags: str,
    expense_time: str = "2026-05-02T00:00:00Z",
) -> dict:
    response = client.post(
        "/api/expenses/manual",
        headers=headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": "餐饮",
            "expense_time": expense_time,
            "tags": tags,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_manual_tags_normalize_filter_export_and_stats(client: TestClient, *, identity) -> None:
    first = _manual(
        client,
        headers=identity.app_headers,
        amount_cents=1200,
        merchant="标签早餐",
        tags=" 真香，AI; 真香 ",
    )
    second = _manual(
        client,
        headers=identity.app_headers,
        amount_cents=500,
        merchant="必要早餐",
        tags="必要",
    )

    assert first["tags"] == "真香, AI"
    assert second["tags"] == "必要"

    tags = client.get("/api/expenses/tags", headers=identity.app_headers)
    assert tags.status_code == 200
    assert set(tags.json()["items"]) == {"真香", "AI", "必要"}

    filtered = client.get(
        "/api/expenses/confirmed?month=2026-05&tag=AI", headers=identity.app_headers
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["items"][0]["merchant"] == "标签早餐"

    missing = client.get(
        "/api/expenses/confirmed?month=2026-05&tag=不存在", headers=identity.app_headers
    )
    assert missing.status_code == 200
    assert missing.json()["total"] == 0

    csv_response = client.get(
        "/api/expenses/export.csv?month=2026-05&tag=真香", headers=identity.app_headers
    )
    assert csv_response.status_code == 200
    assert "标签早餐" in csv_response.text
    assert "必要早餐" not in csv_response.text

    stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200
    stats_body = stats.json()
    assert stats_body["total_amount_cents"] == 1700
    by_tag = {row["tag"]: row for row in stats_body["by_tag"]}
    assert by_tag["真香"] == {"tag": "真香", "amount_cents": 1200, "count": 1}
    assert by_tag["AI"] == {"tag": "AI", "amount_cents": 1200, "count": 1}
    assert by_tag["必要"] == {"tag": "必要", "amount_cents": 500, "count": 1}

    tag_stats = client.get(
        "/api/stats/monthly?month=2026-05&tag=真香", headers=identity.app_headers
    )
    assert tag_stats.status_code == 200
    assert tag_stats.json()["total_amount_cents"] == 1200
    assert tag_stats.json()["count"] == 1


def test_updating_tags_to_blank_clears_filter_links(client: TestClient, *, identity) -> None:
    item = _manual(
        client,
        headers=identity.app_headers,
        amount_cents=1800,
        merchant="可清空标签",
        tags="外卖, 冲动",
    )

    update = client.patch(
        f"/api/expenses/{item['id']}",
        headers=identity.app_headers,
        json={"tags": "   "},
    )
    assert update.status_code == 200
    assert update.json()["tags"] is None

    tags = client.get("/api/expenses/tags", headers=identity.app_headers)
    assert tags.status_code == 200
    assert tags.json()["items"] == []

    filtered = client.get(
        "/api/expenses/confirmed?month=2026-05&tag=外卖", headers=identity.app_headers
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 0


def test_tag_filters_are_ledger_scoped(client: TestClient, *, identity) -> None:
    _manual(
        client,
        headers=identity.app_headers,
        amount_cents=2100,
        merchant="Owner Shared",
        tags="Shared",
    )
    _manual(
        client,
        headers=identity.gray_app_headers,
        amount_cents=3100,
        merchant="Gray Shared",
        tags="Shared",
    )

    owner_page = client.get(
        "/api/expenses/confirmed?month=2026-05&tag=Shared", headers=identity.app_headers
    )
    gray_page = client.get(
        "/api/expenses/confirmed?month=2026-05&tag=Shared", headers=identity.gray_app_headers
    )
    assert owner_page.status_code == 200
    assert gray_page.status_code == 200
    assert [row["merchant"] for row in owner_page.json()["items"]] == ["Owner Shared"]
    assert [row["merchant"] for row in gray_page.json()["items"]] == ["Gray Shared"]

    owner_stats = client.get(
        "/api/stats/monthly?month=2026-05&tag=Shared", headers=identity.app_headers
    )
    gray_stats = client.get(
        "/api/stats/monthly?month=2026-05&tag=Shared", headers=identity.gray_app_headers
    )
    assert owner_stats.json()["total_amount_cents"] == 2100
    assert gray_stats.json()["total_amount_cents"] == 3100

    owner_csv = client.get(
        "/api/expenses/export.csv?month=2026-05&tag=Shared", headers=identity.app_headers
    )
    gray_csv = client.get(
        "/api/expenses/export.csv?month=2026-05&tag=Shared", headers=identity.gray_app_headers
    )
    assert "Owner Shared" in owner_csv.text
    assert "Gray Shared" not in owner_csv.text
    assert "Gray Shared" in gray_csv.text
    assert "Owner Shared" not in gray_csv.text


def test_import_rows_syncs_tag_relation_rows(client: TestClient) -> None:
    preview = parse_csv_preview(
        'amount_yuan,merchant,tags\n3.00,Imported,"外卖，AI，外卖"\n'
    )

    with SessionLocal() as db:
        inserted = import_rows(db, tenant_id="owner", rows=preview.rows)
        assert inserted == 1
        expense = db.scalar(select(Expense).where(Expense.merchant == "Imported"))
        assert expense is not None
        assert expense.tags == "外卖, AI"
        link_count = int(
            db.scalar(
                select(func.count(ExpenseTag.id))
                .where(ExpenseTag.tenant_id == "owner")
                .where(ExpenseTag.expense_id == expense.id)
            )
            or 0
        )
        tag_names = set(
            db.scalars(select(Tag.name).where(Tag.tenant_id == "owner")).all()
        )

    assert link_count == 2
    assert tag_names == {"外卖", "AI"}
