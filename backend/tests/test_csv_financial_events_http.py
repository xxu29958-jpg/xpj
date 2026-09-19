"""Real export -> saved import -> human review journeys on the PostgreSQL lane."""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import StringIO
from threading import Barrier

import pytest
from api_contract_helpers import confirm_expense_api
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    CsvImportBatch,
    CsvImportEvent,
    CsvImportRow,
    ExchangeRate,
    Expense,
    ExpenseOffsetFact,
    ExpenseOffsetRevision,
    ExpenseRevision,
    FxRate,
)
from app.services.csv_import_batch_service import _events as csv_events
from tests.expense_correction_support import idem, manual_confirmed
from tests.test_csv_import_batches_http_flow import _demote_owner_ledger_to_viewer
from tests.test_expense_offset_lifecycle import _create_refund, _foreign_expense, _seed_usd_rate


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


def _rate_facts() -> tuple[list, list]:
    with SessionLocal() as db:
        return (
            list(db.execute(select(
                ExchangeRate.id, ExchangeRate.tenant_id, ExchangeRate.home_currency_code,
                ExchangeRate.currency_code, ExchangeRate.rate_date, ExchangeRate.rate_to_cny,
                ExchangeRate.source, ExchangeRate.row_version, ExchangeRate.updated_at,
            ).order_by(ExchangeRate.id))),
            list(db.execute(select(
                FxRate.id, FxRate.source, FxRate.home_currency_code, FxRate.currency_code,
                FxRate.rate_date, FxRate.rate_to_home, FxRate.verified_through, FxRate.updated_at,
            ).order_by(FxRate.id))),
        )


def _event_mappings(ledger_id: str) -> list:
    with SessionLocal() as db:
        return list(db.execute(select(
            CsvImportEvent.id, CsvImportEvent.entry_kind, CsvImportEvent.source_event_public_id,
            CsvImportEvent.source_row_id, CsvImportEvent.expense_id, CsvImportEvent.offset_id,
        ).where(CsvImportEvent.tenant_id == ledger_id).order_by(CsvImportEvent.id)))


def _offset_first(content: bytes) -> bytes:
    reader = csv.DictReader(StringIO(content.decode("utf-8-sig")))
    rows = sorted(reader, key=lambda row: row["entry_kind"] != "offset")
    assert [row["entry_kind"] for row in rows] == ["offset", "expense"]
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


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


def test_native_csv_review_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/imports/csv/00000000-0000-4000-8000-000000000001/rows/2/review",
        json={"reason": "复核导入事件"},
    )
    assert response.status_code == 401, response.text


@pytest.mark.parametrize("kind", ["refund", "chargeback", "reversal"])
def test_export_reuploaded_to_original_ledger_matches_facts_and_viewer_cannot_review(
    client: TestClient, identity, kind: str,
) -> None:
    expense = manual_confirmed(client, identity, amount_cents=10000)
    payload = {
        "kind": kind, "accounting_date": "2026-05-05", "reason": "原始经济事件",
        "expected_row_version": expense["row_version"],
    }
    if kind != "reversal":
        payload["original_amount_minor"] = 2500
    response = client.post(
        f"/api/expenses/{expense['id']}/offsets", headers=idem(identity.app_headers), json=payload,
    )
    assert response.status_code == 201, response.text
    original = response.json()
    offset, = original["active_offsets"]
    content = _export(client, identity.app_headers)
    before = _fact_counts("owner")

    batches = []
    for _ in range(2):
        batch = _batch(client, identity.app_headers, content)
        batches.append(batch)
        assert _apply(client, identity.app_headers, batch)["inserted_count"] == 0
        assert _apply(client, identity.app_headers, batch)["inserted_count"] == 0
        saved = _rows(client, identity.app_headers, batch)
        assert saved["batch"]["matched_rows"] == 2
        assert saved["batch"]["review_rows"] == 0
        root_row, = [row for row in saved["items"] if row["entry_kind"] == "expense"]
        offset_row, = [row for row in saved["items"] if row["entry_kind"] == "offset"]
        assert root_row["status"] == offset_row["status"] == "matched"
        assert root_row["expense_id"] is None and offset_row["expense_id"] is None
        assert root_row["resolved_expense_id"] == offset_row["resolved_expense_id"] == expense["id"]
        assert offset_row["resolved_offset_public_id"] == offset["public_id"]
        assert _fact_counts("owner") == before
    assert batches[0] != batches[1]
    assert _bundle(client, identity.app_headers, expense["id"]) == original
    hidden = client.get(f"/api/imports/csv/{batches[0]}", headers=identity.gray_app_headers)
    assert hidden.status_code == 404, hidden.text

    _demote_owner_ledger_to_viewer()
    assert _rows(client, identity.app_headers, batches[0])["total"] == 2
    denied = client.post(
        f"/api/imports/csv/{batches[0]}/rows/{offset_row['line_number']}/review",
        headers=idem(identity.app_headers),
        json={"expense_id": expense["id"], "expected_row_version": original["root"]["row_version"],
              "reason": "只读成员不能确认"},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"] == "permission_denied"
    assert _fact_counts("owner") == before


def test_foreign_out_of_order_import_resumes_with_frozen_money_and_independent_offset_category(
    client: TestClient, identity,
) -> None:
    content, source = _foreign_source_export(client, identity)
    target = identity.gray_app_headers
    for rate_date, rate in (("2026-05-04", "9"), ("2026-05-05", "10")):
        seeded = client.put(
            f"/api/exchange-rates/USD/{rate_date}", headers=idem(target),
            json={"expected_row_version": 0, "home_currency_code": "CNY", "currency_code": "USD",
                  "rate_date": rate_date, "rate_to_cny": rate, "source": "manual"},
        )
        assert seeded.status_code == 200, seeded.text
    rates_before = _rate_facts()
    batch = _batch(client, target, _offset_first(content))
    preview = _rows(client, target, batch)
    refund = preview["items"][0]
    assert refund["entry_kind"] == "offset" and refund["offset_kind"] == "refund"
    assert refund["source_event_public_id"] == source["active_offsets"][0]["public_id"]
    assert refund["source_root_public_id"] == source["root"]["public_id"]
    assert refund["exchange_rate_source"] == "manual"
    assert Decimal(refund["exchange_rate_to_cny"]) == Decimal("8")

    first = _apply(client, target, batch, size=1)
    assert first["inserted_count"] == 0
    assert first["remaining_valid_rows"] == 1
    assert _fact_counts("tester_1") == (0, 0, 0, 0)
    reopened = _rows(client, target, batch)
    assert reopened["items"][0]["status"] == "review"
    assert reopened["items"][0]["expense_id"] is None
    assert reopened["batch"]["review_rows"] == 1
    assert _apply(client, target, batch, size=1)["inserted_count"] == 1
    saved = _rows(client, target, batch)
    root_row, = [row for row in saved["items"] if row["entry_kind"] == "expense"]
    expense_id = root_row["expense_id"]
    pending = client.get(f"/api/expenses/{expense_id}", headers=target)
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "pending"
    assert pending.json()["amount_cents"] == 70000
    confirmed = confirm_expense_api(client, expense_id, headers=target)
    assert confirmed.status_code == 200, confirmed.text
    reviewed = client.post(
        f"/api/imports/csv/{batch}/rows/{refund['line_number']}/review", headers=idem(target),
        json={"expense_id": expense_id, "expected_row_version": confirmed.json()["row_version"],
              "reason": "核对原币订单与退款凭据"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "applied"
    assert reviewed.json()["expense_id"] is None
    imported = _bundle(client, target, expense_id)
    imported_offset, = imported["active_offsets"]
    assert reviewed.json()["resolved_offset_public_id"] == imported_offset["public_id"]
    assert imported["root"]["home_currency"] == source["root"]["home_currency"] == "CNY"
    assert imported_offset["home_currency_code"] == "CNY"
    for actual, original in ((imported["root"], source["root"]),
                             (imported_offset, source["active_offsets"][0])):
        for field in ("original_currency_code", "original_amount_minor",
                      "amount_cents", "category", "exchange_rate_date"):
            assert actual[field] == original[field], field
        assert Decimal(actual["exchange_rate_to_cny"]) == Decimal(original["exchange_rate_to_cny"])
        assert actual["exchange_rate_source"] == "imported"
    assert imported_offset["accounting_date"] == "2026-05-05"
    assert imported_offset["category"] == "售后"
    assert imported["financial_summary"]["lineage_home_net_cents"] == 50000
    assert _rate_facts() == rates_before
    stats = client.get("/api/stats/monthly?month=2026-05", headers=target)
    assert stats.status_code == 200, stats.text
    assert stats.json()["total_amount_cents"] == 50000
    assert {row["category"]: row["amount_cents"] for row in stats.json()["by_category"]} == {
        "购物": 70000, "售后": -20000,
    }
    before_reupload = _fact_counts("tester_1")
    second_batch = _batch(client, target, content)
    assert _apply(client, target, second_batch)["inserted_count"] == 0
    assert _rows(client, target, second_batch)["batch"]["matched_rows"] == 2
    assert _fact_counts("tester_1") == before_reupload
    assert _rate_facts() == rates_before


def test_filtered_refund_resumes_after_root_arrives_and_occ_then_ack_replay_preserve_original_task(
    client: TestClient, identity,
) -> None:
    source_root = manual_confirmed(client, identity, amount_cents=10000)
    source = _create_refund(client, identity, source_root, accounting_date="2026-09-05")
    target = identity.gray_app_headers
    offset_batch = _batch(client, target, _export(client, identity.app_headers, month="2026-09"))
    assert _apply(client, target, offset_batch)["inserted_count"] == 0
    original_row, = _rows(client, target, offset_batch)["items"]
    assert original_row["status"] == "review"
    assert original_row["entry_kind"] == "offset"
    assert original_row["source_root_public_id"] == source_root["public_id"]
    assert _fact_counts("tester_1") == (0, 0, 0, 0)
    endpoint = f"/api/imports/csv/{offset_batch}/rows/{original_row['line_number']}/review"
    denied_root = client.post(
        endpoint, headers=idem(target),
        json={"expense_id": source_root["id"], "expected_row_version": source["root"]["row_version"],
              "reason": "文件标识不能跨账本授权"},
    )
    assert denied_root.status_code == 404, denied_root.text
    assert _rows(client, target, offset_batch)["items"][0]["status"] == "review"
    assert _fact_counts("tester_1") == (0, 0, 0, 0)

    root_batch = _batch(client, target, _export(client, identity.app_headers, month="2026-05"))
    assert _apply(client, target, root_batch)["inserted_count"] == 1
    root_row, = _rows(client, target, root_batch)["items"]
    expense_id = root_row["expense_id"]
    confirmed = confirm_expense_api(client, expense_id, headers=target)
    assert confirmed.status_code == 200, confirmed.text
    old_version = confirmed.json()["row_version"]
    corrected = client.post(
        f"/api/expenses/{expense_id}/corrections", headers=idem(target),
        json={"expected_row_version": old_version, "reason": "另一端补充说明", "note": "核对后的订单备注"},
    )
    assert corrected.status_code == 201, corrected.text
    before_review = _fact_counts("tester_1")
    payload = {"expense_id": expense_id, "expected_row_version": old_version, "reason": "确认原导入退款"}
    stale = client.post(endpoint, headers=idem(target), json=payload)
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"
    resumed_row, = _rows(client, target, offset_batch)["items"]
    assert resumed_row["status"] == "review"
    for field in ("line_number", "source_event_public_id", "source_root_public_id", "amount_cents", "offset_kind"):
        assert resumed_row[field] == original_row[field]
    assert _fact_counts("tester_1") == before_review
    payload["expected_row_version"] = _bundle(client, target, expense_id)["root"]["row_version"]
    headers = idem(target)
    accepted = client.post(endpoint, headers=headers, json=payload)
    assert accepted.status_code == 200, accepted.text
    after_accept = _fact_counts("tester_1")
    replayed = client.post(endpoint, headers=headers, json=payload)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == accepted.json()
    assert _fact_counts("tester_1") == after_accept
    result = _bundle(client, target, expense_id)
    offset, = result["active_offsets"]
    assert accepted.json()["status"] == "applied"
    assert accepted.json()["resolved_expense_id"] == expense_id
    assert accepted.json()["resolved_offset_public_id"] == offset["public_id"]
    assert offset["original_amount_minor"] == 2500
    assert result["financial_summary"]["lineage_home_net_cents"] == 7500
    assert _rows(client, target, offset_batch)["batch"]["review_rows"] == 0


def test_duplicate_saved_refund_tasks_share_matched_filters_and_changed_event_conflicts(
    client: TestClient, identity,
) -> None:
    source_root = manual_confirmed(client, identity, amount_cents=10000)
    source = _create_refund(client, identity, source_root, accounting_date="2026-09-05")
    source_offset, = source["active_offsets"]
    target = identity.gray_app_headers
    content = _export(client, identity.app_headers, month="2026-09")
    first_batch = _batch(client, target, content)
    second_batch = _batch(client, target, content)
    for batch in (first_batch, second_batch):
        assert _apply(client, target, batch)["inserted_count"] == 0
        staged = _rows(client, target, batch)
        row, = staged["items"]
        assert row["status"] == "review"
        assert row["source_event_public_id"] == source_offset["public_id"]
        assert staged["batch"]["review_rows"] == 1
        assert staged["batch"]["matched_rows"] == 0
    assert _fact_counts("tester_1") == (0, 0, 0, 0)

    root_batch = _batch(client, target, _export(client, identity.app_headers, month="2026-05"))
    assert _apply(client, target, root_batch)["inserted_count"] == 1
    root_row, = _rows(client, target, root_batch)["items"]
    expense_id = root_row["expense_id"]
    confirmed = confirm_expense_api(client, expense_id, headers=target)
    assert confirmed.status_code == 200, confirmed.text
    first_row, = _rows(client, target, first_batch)["items"]
    accepted = client.post(
        f"/api/imports/csv/{first_batch}/rows/{first_row['line_number']}/review", headers=idem(target),
        json={"expense_id": expense_id, "expected_row_version": confirmed.json()["row_version"],
              "reason": "核对首个保存任务的退款"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "applied"
    saved = _rows(client, target, second_batch)
    matched = _rows(client, target, second_batch, status="matched")
    waiting = _rows(client, target, second_batch, status="review")
    assert saved["total"] == matched["total"] == 1
    assert matched["items"] == saved["items"]
    second_row, = saved["items"]
    assert second_row["status"] == "matched"
    assert second_row["expense_id"] is None
    assert second_row["resolved_expense_id"] == expense_id
    assert second_row["resolved_offset_public_id"] == accepted.json()["resolved_offset_public_id"]
    assert waiting["total"] == 0 and waiting["items"] == []
    for page in (saved, matched, waiting):
        assert page["batch"]["matched_rows"] == 1
        assert page["batch"]["review_rows"] == 0
    detail = client.get(f"/api/imports/csv/{second_batch}", headers=target)
    assert detail.status_code == 200, detail.text
    assert detail.json()["matched_rows"] == 1 and detail.json()["review_rows"] == 0

    original = _bundle(client, target, expense_id)
    counts = _fact_counts("tester_1")
    replay_headers = idem(target)
    replay_payload = {
        "expense_id": expense_id, "expected_row_version": original["root"]["row_version"],
        "reason": "返回第二个保存任务确认已有结果",
    }
    for _ in range(2):
        replay = client.post(
            f"/api/imports/csv/{second_batch}/rows/{second_row['line_number']}/review",
            headers=replay_headers, json=replay_payload,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["status"] == "matched"
        assert replay.json()["resolved_offset_public_id"] == second_row["resolved_offset_public_id"]
        assert _fact_counts("tester_1") == counts
        assert _bundle(client, target, expense_id) == original

    mappings = _event_mappings("tester_1")
    corrected = client.post(
        f"/api/expenses/{source_root['id']}/offsets/{source_offset['public_id']}/corrections",
        headers=idem(identity.app_headers),
        json={"original_amount_minor": 2000, "accounting_date": "2026-09-05",
              "category": source_offset["category"], "offset_reason": "按最终退款额更新",
              "correction_reason": "源账本更正退款金额", "expected_row_version": source_offset["row_version"]},
    )
    assert corrected.status_code == 201, corrected.text
    changed_batch = _batch(client, target, _export(client, identity.app_headers, month="2026-09"))
    changed_row, = _rows(client, target, changed_batch)["items"]
    assert changed_row["status"] == "valid"
    assert changed_row["source_event_public_id"] == source_offset["public_id"]
    assert changed_row["amount_cents"] == changed_row["original_amount_minor"] == 2000
    assert changed_row["stream_amount_cents"] == -2000
    assert changed_row["lineage_home_net_cents"] == 8000
    assert _apply(client, target, changed_batch)["inserted_count"] == 0
    conflicted = _rows(client, target, changed_batch)
    conflict, = conflicted["items"]
    assert conflict["status"] == "conflict"
    assert conflict["error_code"] == "import_event_conflict"
    assert conflicted["batch"]["error_rows"] == 1
    assert conflicted["batch"]["matched_rows"] == 0
    assert _event_mappings("tester_1") == mappings
    assert _fact_counts("tester_1") == counts
    assert _bundle(client, target, expense_id) == original
    assert original["active_offsets"][0]["original_amount_minor"] == 2500
    assert original["financial_summary"]["lineage_home_net_cents"] == 7500


def test_historical_empty_quote_review_preserves_raw_money_and_reupload_matches(
    client: TestClient, identity,
) -> None:
    _seed_usd_rate(client, identity, "2026-05-04", "7")
    source_root = _foreign_expense(client, identity, "旧文件的原币消费")
    content = _export(client, identity.app_headers)
    target = identity.gray_app_headers
    rates = _rate_facts()
    quoted_batch = _batch(client, target, content)
    quoted_row, = _rows(client, target, quoted_batch)["items"]
    replacement = client.post(
        f"/api/imports/csv/{quoted_batch}/rows/{quoted_row['line_number']}/review", headers=idem(target),
        json={"reason": "已有报价不得替换", "manual_exchange_rate": "7", "exchange_rate_date": "2026-05-05"},
    )
    assert replacement.status_code == 422, replacement.text
    assert replacement.json()["error"] == "currency_snapshot_invalid"
    assert _rows(client, target, quoted_batch)["items"] == [quoted_row]
    assert _event_mappings("tester_1") == []
    assert _fact_counts("tester_1") == (0, 0, 0, 0)

    reader = csv.DictReader(StringIO(content.decode("utf-8-sig")))
    source_row, = list(reader)
    quote_fields = ("exchange_rate_to_cny", "exchange_rate_date", "exchange_rate_source")
    for field in quote_fields:
        source_row[field] = ""
    historical = StringIO()
    writer = csv.DictWriter(historical, fieldnames=reader.fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerow(source_row)
    historical_content = historical.getvalue().encode("utf-8")
    batch = _batch(client, target, historical_content)
    preview, = _rows(client, target, batch)["items"]
    assert preview["status"] == "valid"
    assert all(preview[field] is None for field in quote_fields)
    assert all(preview["event_input"][field] == "" for field in quote_fields)
    assert _apply(client, target, batch)["inserted_count"] == 0
    staged, = _rows(client, target, batch)["items"]
    assert staged["status"] == "review"
    assert staged["event_input"] == preview["event_input"]
    mappings = _event_mappings("tester_1")
    endpoint = f"/api/imports/csv/{batch}/rows/{staged['line_number']}/review"
    payload = {"reason": "核对旧文件的原币与本位币金额", "manual_exchange_rate": "8",
               "exchange_rate_date": "2026-05-04"}
    wrong_quote = client.post(endpoint, headers=idem(target), json=payload)
    assert wrong_quote.status_code == 422, wrong_quote.text
    assert wrong_quote.json()["error"] == "currency_snapshot_invalid"
    assert _rows(client, target, batch)["items"] == [staged]
    assert _event_mappings("tester_1") == mappings
    assert _fact_counts("tester_1") == (0, 0, 0, 0)
    assert _rate_facts() == rates

    payload["manual_exchange_rate"] = "7"
    reviewed = client.post(endpoint, headers=idem(target), json=payload)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "applied"
    expense_id = reviewed.json()["expense_id"]
    saved, = _rows(client, target, batch)["items"]
    assert saved["event_input"] == preview["event_input"]
    assert Decimal(saved["exchange_rate_to_cny"]) == Decimal("7")
    assert saved["exchange_rate_date"] == "2026-05-04"
    assert saved["exchange_rate_source"] == "manual"
    assert saved["amount_cents"] == staged["amount_cents"] == 70000
    assert saved["original_amount_minor"] == staged["original_amount_minor"] == 10000
    assert saved["home_currency_code"] == staged["home_currency_code"] == "CNY"
    assert saved["original_currency_code"] == staged["original_currency_code"] == "USD"
    pending = client.get(f"/api/expenses/{expense_id}", headers=target)
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "pending"
    confirmed = confirm_expense_api(client, expense_id, headers=target)
    assert confirmed.status_code == 200, confirmed.text
    for field in ("original_currency_code", "original_amount_minor", "amount_cents", "exchange_rate_date"):
        assert confirmed.json()[field] == source_root[field]
    assert confirmed.json()["exchange_rate_source"] == "imported"
    assert Decimal(confirmed.json()["exchange_rate_to_cny"]) == Decimal("7")

    facts = _fact_counts("tester_1")
    mappings = _event_mappings("tester_1")
    original = _bundle(client, target, expense_id)
    repeated_batch = _batch(client, target, historical_content)
    assert _apply(client, target, repeated_batch)["inserted_count"] == 0
    repeated = _rows(client, target, repeated_batch)
    repeated_row, = repeated["items"]
    assert repeated_row["status"] == "matched"
    assert repeated_row["expense_id"] is None
    assert repeated_row["resolved_expense_id"] == expense_id
    assert repeated_row["event_input"] == preview["event_input"]
    assert repeated["batch"]["matched_rows"] == 1 and repeated["batch"]["review_rows"] == 0
    assert _event_mappings("tester_1") == mappings
    assert _fact_counts("tester_1") == facts
    assert _bundle(client, target, expense_id) == original
    assert _rate_facts() == rates


def test_missing_refund_quote_review_in_second_batch_becomes_canonical_for_replays(
    client: TestClient, identity,
) -> None:
    _, source = _foreign_source_export(client, identity)
    source_offset, = source["active_offsets"]
    target = identity.gray_app_headers
    content = _export(client, identity.app_headers, category="售后")
    reader = csv.DictReader(StringIO(content.decode("utf-8-sig")))
    source_row, = list(reader)
    assert source_row["entry_kind"] == "offset"
    quote_fields = ("exchange_rate_to_cny", "exchange_rate_date", "exchange_rate_source")
    for field in quote_fields:
        source_row[field] = ""
    historical = StringIO()
    writer = csv.DictWriter(historical, fieldnames=reader.fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerow(source_row)
    historical_content = historical.getvalue().encode("utf-8")
    first_batch = _batch(client, target, historical_content)
    second_batch = _batch(client, target, historical_content)
    for batch in (first_batch, second_batch):
        assert _apply(client, target, batch)["inserted_count"] == 0
        row, = _rows(client, target, batch)["items"]
        assert row["status"] == "review"
        assert all(row[field] is None for field in quote_fields)
    source_batch_query = (
        select(CsvImportBatch.public_id).select_from(CsvImportEvent)
        .join(CsvImportRow, CsvImportRow.id == CsvImportEvent.source_row_id)
        .join(CsvImportBatch, CsvImportBatch.id == CsvImportRow.batch_id)
        .where(CsvImportEvent.tenant_id == "tester_1", CsvImportEvent.entry_kind == "offset",
               CsvImportEvent.source_event_public_id == source_offset["public_id"])
    )
    with SessionLocal() as db:
        assert db.scalar(source_batch_query) == first_batch
    root_batch = _batch(client, target, _export(client, identity.app_headers, category="购物"))
    assert _apply(client, target, root_batch)["inserted_count"] == 1
    root_row, = _rows(client, target, root_batch)["items"]
    expense_id = root_row["expense_id"]
    confirmed = confirm_expense_api(client, expense_id, headers=target)
    assert confirmed.status_code == 200, confirmed.text
    second_row, = _rows(client, target, second_batch)["items"]
    accepted = client.post(
        f"/api/imports/csv/{second_batch}/rows/{second_row['line_number']}/review", headers=idem(target),
        json={"expense_id": expense_id, "expected_row_version": confirmed.json()["row_version"],
              "reason": "在第二个保存任务补齐退款报价", "manual_exchange_rate": "8",
              "exchange_rate_date": "2026-05-05"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "applied"
    with SessionLocal() as db:
        assert db.scalar(source_batch_query) == second_batch
    saved, = _rows(client, target, second_batch)["items"]
    assert Decimal(saved["exchange_rate_to_cny"]) == Decimal("8")
    assert all(saved["event_input"][field] == "" for field in quote_fields)
    original = _bundle(client, target, expense_id)
    offset, = original["active_offsets"]
    assert offset["amount_cents"] == 20000 and offset["original_amount_minor"] == 2500
    assert offset["exchange_rate_source"] == "imported"
    assert original["financial_summary"]["lineage_home_net_cents"] == 50000
    counts = _fact_counts("tester_1")
    mappings = _event_mappings("tester_1")
    first_row, = _rows(client, target, first_batch)["items"]
    resumed = client.post(
        f"/api/imports/csv/{first_batch}/rows/{first_row['line_number']}/review", headers=idem(target),
        json={"expense_id": expense_id, "expected_row_version": original["root"]["row_version"],
              "reason": "回到首个保存任务查看已接受的退款"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "matched"
    assert resumed.json()["resolved_offset_public_id"] == offset["public_id"]
    repeated_batch = _batch(client, target, historical_content)
    assert _apply(client, target, repeated_batch)["inserted_count"] == 0
    repeated = _rows(client, target, repeated_batch)
    repeated_row, = repeated["items"]
    assert repeated_row["status"] == "matched"
    assert repeated_row["resolved_offset_public_id"] == offset["public_id"]
    assert repeated["batch"]["matched_rows"] == 1 and repeated["batch"]["review_rows"] == 0
    assert _event_mappings("tester_1") == mappings
    assert _fact_counts("tester_1") == counts
    assert _bundle(client, target, expense_id) == original


@pytest.mark.real_db
def test_concurrent_native_purchase_batches_commit_one_pending_fact_and_mapping(
    client: TestClient, identity, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = manual_confirmed(client, identity, amount_cents=10000)
    content = _export(client, identity.app_headers)
    target = identity.gray_app_headers
    batches = [_batch(client, target, content) for _ in range(2)]
    barrier = Barrier(2)
    claim_event = csv_events.claim_csv_event

    def synchronized_claim(db, row):
        # Both HTTP requests reach the real PG unique claim before either can win.
        barrier.wait(timeout=10)
        return claim_event(db, row)

    monkeypatch.setattr(csv_events, "claim_csv_event", synchronized_claim)

    def apply_once(batch):
        worker = TestClient(client.app)
        try:
            return _apply(worker, target, batch)
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply_once, batches, timeout=20))
    assert sorted(result["inserted_count"] for result in results) == [0, 1]
    assert all(result["remaining_valid_rows"] == 0 for result in results)
    rows = [_rows(client, target, batch)["items"][0] for batch in batches]
    assert sorted(row["status"] for row in rows) == ["applied", "matched"]
    inserted, = [row for row in rows if row["status"] == "applied"]
    matched, = [row for row in rows if row["status"] == "matched"]
    expense_id = inserted["expense_id"]
    assert matched["expense_id"] is None
    assert all(row["resolved_expense_id"] == expense_id for row in rows)
    assert all(row["source_event_public_id"] == source_root["public_id"] for row in rows)
    assert _fact_counts("tester_1") == (1, 0, 0, 0)
    mappings = _event_mappings("tester_1")
    mapping, = mappings
    assert mapping.entry_kind == "expense"
    assert mapping.source_event_public_id == source_root["public_id"]
    assert mapping.expense_id == expense_id and mapping.offset_id is None
    pending = client.get(f"/api/expenses/{expense_id}", headers=target)
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "pending"
    assert pending.json()["amount_cents"] == 10000
