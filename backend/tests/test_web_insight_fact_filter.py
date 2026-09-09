"""Real PostgreSQL postconditions for Insights → confirmed-fact remediation."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import unescape
from urllib.parse import parse_qs, urljoin, urlsplit
from uuid import uuid4

import pytest
from _web_bulk_test_support import bulk_snapshot_fields
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense, LedgerMember
from app.services.currency_binding_service import resolve_write_capability
from tests.web_expense_fact_test_support import create_confirmed, owner_member_id, row_version

pytestmark = pytest.mark.real_db


def _anchors(body: str) -> list[dict[str, str]]:
    return [
        {name: unescape(value) for name, value in re.findall(r'([\w-]+)="([^"]*)"', tag)}
        for tag in re.findall(r"<a\b[^>]*>", body)
    ]


def _row_hrefs(body: str) -> list[str]:
    return [
        link["href"] for link in _anchors(body)
        if "timeline-row-detail" in link.get("class", "").split()
    ]


def _hidden_form(body: str, action: str) -> dict[str, str]:
    form = re.search(rf'<form\b[^>]*action="{re.escape(action)}"[^>]*>(.*?)</form>', body, re.S)
    assert form is not None, action
    fields = {}
    for tag in re.findall(r"<input\b[^>]*>", form.group(1)):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
        if attrs.get("type") == "hidden" and "name" in attrs:
            fields[attrs["name"]] = unescape(attrs.get("value", ""))
    return fields


def _assert_query(href: str, path: str, **expected: str) -> None:
    parsed = urlsplit(href)
    assert parsed.path == path
    query = parse_qs(parsed.query)
    for name, value in expected.items():
        assert query.get(name) == [value], (href, name)


def _seed_categories(
    categories: list[str], *, ledger_id: str = "owner", status: str = "confirmed", month: int | None = None,
) -> list[int]:
    # Current commands normalize these tokens. Seed existing dirty facts with
    # the real writer proof, as the data-quality fixtures do; no trigger bypass.
    with SessionLocal() as db:
        resolve_write_capability(db)
        rows = [
            Expense(
                tenant_id=ledger_id, amount_cents=500, merchant=f"分类样本 {index}",
                category=category, source="pytest", status=status, duplicate_status="none",
                expense_time=datetime(2026, month or index % 6 + 1, 4, 12, tzinfo=UTC),
                confirmed_at=datetime(2026, month or index % 6 + 1, 4, 12, tzinfo=UTC),
            )
            for index, category in enumerate(categories)
        ]
        db.add_all(rows)
        db.commit()
        return [row.id for row in rows]


def _mark_uncategorized(expense_ids: list[int]) -> None:
    with SessionLocal() as db:
        resolve_write_capability(db)
        for expense_id in expense_ids:
            row = db.get(Expense, expense_id)
            assert row is not None
            # Expense.category is NOT NULL; an empty string is a stored
            # uncategorized fact, while inserting None would default to "其他".
            row.category = ""
        db.commit()


def _quality(client: TestClient, identity) -> dict:
    response = client.get("/api/insights/data-quality", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    return response.json()


def _intervening_correction(client: TestClient, identity, expense_id: int) -> None:
    response = client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": row_version(client, expense_id, identity),
            "merchant": "另一端更正商家", "reason": "产生真实并发版本",
        },
    )
    assert response.status_code == 201, response.text


def test_missing_category_matches_all_month_health_roots_and_pagination(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    monkeypatch.setattr("app.routes.web_app._CONFIRMED_PAGE_SIZE", 2)
    refunded_id = create_confirmed(web_client, identity=identity)
    refund = web_client.post(
        f"/api/expenses/{refunded_id}/offsets",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "kind": "refund", "accounting_date": "2026-05-05", "original_amount_minor": 100,
            "reason": "真实退款不应变成第二笔待分类记录",
            "expected_row_version": row_version(web_client, refunded_id, identity),
        },
    )
    assert refund.status_code == 201, refund.text
    _mark_uncategorized([refunded_id])
    expected_ids = {refunded_id, *_seed_categories([
        "", "\t\u3000", " 未分类 ", "\u00a0未分類\u3000", " NoNe ", "\u202fNuLl\u205f",
    ])}
    _seed_categories(["餐饮", "其他", "\u0085none\u0085", "none food"])
    _seed_categories([""], status="pending")
    foreign_ids = _seed_categories([""], ledger_id="tester_1")
    health = _quality(web_client, identity)
    assert health["missing_category_confirmed"] == len(expected_ids)
    assert health["missing_category_pending"] == 1
    assert health["missing_category"] == len(expected_ids) + 1

    href = "/web/confirmed?ledger_id=owner&filter=missing_category&month=2026-12"
    seen = []
    for page_number in range(1, 5):
        page = web_client.get(href)
        assert page.status_code == 200, page.text
        assert f"共 {len(expected_ids)} 条" in page.text
        for row_href in _row_hrefs(page.text):
            expense_id = int(urlsplit(row_href).path.split("/")[3])
            _assert_query(
                row_href, f"/web/expenses/{expense_id}/edit", ledger_id="owner",
                return_to="confirmed", return_filter="missing_category",
            )
            seen.append(expense_id)
        next_links = [link["href"] for link in _anchors(page.text) if link.get("rel") == "next"]
        if page_number < 4:
            assert len(next_links) == 1
            href = urljoin("/web/confirmed", next_links[0])
            _assert_query(href, "/web/confirmed", ledger_id="owner", filter="missing_category",
                          page=str(page_number + 1))
            assert "month" not in parse_qs(urlsplit(href).query)
        else:
            assert next_links == []
    assert len(seen) == len(set(seen)) == health["missing_category_confirmed"]
    assert set(seen) == expected_ids
    foreign = web_client.get("/web/confirmed?ledger_id=tester_1&filter=missing_category")
    assert foreign.status_code == 200, foreign.text
    assert [int(urlsplit(href).path.split("/")[3]) for href in _row_hrefs(foreign.text)] == foreign_ids


def test_missing_category_batch_keeps_context_through_errors_and_reduces_health(
    web_client: TestClient, *, identity,
) -> None:
    expense_ids = [create_confirmed(web_client, identity=identity, merchant="末页待分类")]
    _mark_uncategorized(expense_ids)
    remaining_ids = set(_seed_categories([""] * 50, month=6))
    page = web_client.get("/web/confirmed?ledger_id=owner&filter=missing_category&page=2")
    assert page.status_code == 200, page.text
    assert [int(urlsplit(href).path.split("/")[3]) for href in _row_hrefs(page.text)] == expense_ids
    action = "/web/confirmed/batch-update"
    data = {**_hidden_form(page.text, action), **bulk_snapshot_fields(web_client, expense_ids, identity=identity),
            "action": "set_category", "category": "交通", "reason": ""}
    assert data["ledger_id"] == "owner" and data["filter"] == "missing_category"
    assert data["page"] == "2"
    before = _quality(web_client, identity)
    assert before["missing_category_confirmed"] == 51
    invalid = web_client.post(action, data=data, follow_redirects=False)
    assert invalid.status_code == 422, invalid.text
    assert "请说明这次批量更正的原因" in invalid.text
    invalid_context = _hidden_form(invalid.text, action)
    assert invalid_context["filter"] == "missing_category" and invalid_context["page"] == "2"

    _intervening_correction(web_client, identity, expense_ids[0])
    data["reason"] = "从体检补齐分类"
    conflict = web_client.post(action, data=data, follow_redirects=False)
    assert conflict.status_code == 409, conflict.text
    retained = _hidden_form(conflict.text, action)
    assert retained["ledger_id"] == "owner" and retained["filter"] == "missing_category"
    assert retained["page"] == "2"
    assert len(_row_hrefs(conflict.text)) == 1
    assert _quality(web_client, identity)["missing_category_confirmed"] == 51

    # The user reviews the refreshed selection before submitting a new intent.
    data.update(retained)
    data.update(bulk_snapshot_fields(web_client, expense_ids, identity=identity))
    data["idempotency_key"] = str(uuid4())
    success = web_client.post(action, data=data, follow_redirects=False)
    assert success.status_code == 303, success.text
    _assert_query(success.headers["location"], "/web/confirmed", ledger_id="owner", filter="missing_category")
    after_page = web_client.get(success.headers["location"])
    assert after_page.status_code == 200, after_page.text
    after_hrefs = _row_hrefs(after_page.text)
    assert len(after_hrefs) == 50
    assert {int(urlsplit(href).path.split("/")[3]) for href in after_hrefs} == remaining_ids
    assert _hidden_form(after_page.text, action)["page"] == "1"
    assert _hidden_form(after_page.text, action)["filter"] == "missing_category"
    after = _quality(web_client, identity)
    assert after["missing_category_confirmed"] == 50
    assert before["missing_category"] - after["missing_category"] == 1
    for expense_id in expense_ids:
        stored = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
        assert stored.status_code == 200, stored.text
        assert stored.json()["category"] == "交通"


def test_reports_fact_correction_keeps_original_month_through_422_409_and_success(
    web_client: TestClient, *, identity,
) -> None:
    expense_id = create_confirmed(web_client, identity=identity, merchant="月报原始商家")
    origin = {"return_to": "reports", "return_month": "2026-05", "return_home_currency_code": "CNY",
        "return_granularity": "week", "return_ranking_metric": "count", "return_merchant_category": "餐饮"}
    report_task = {"month": "2026-05", "home_currency_code": "CNY", "granularity": "week",
        "ranking_metric": "count", "merchant_category": "餐饮"}
    report = web_client.get("/web/reports", params={"ledger_id": "owner", **report_task})
    assert report.status_code == 200, report.text
    fact_path = f"/web/expenses/{expense_id}/edit"
    fact_href = next(link["href"] for link in _anchors(report.text) if urlsplit(link["href"]).path == fact_path)
    _assert_query(fact_href, fact_path, ledger_id="owner", **origin)
    detail = web_client.get(fact_href)
    assert detail.status_code == 200, detail.text
    form_path = f"/web/expenses/{expense_id}/correct"
    form_href = next(link["href"] for link in _anchors(detail.text) if urlsplit(link["href"]).path == form_path)
    form = web_client.get(form_href)
    assert form.status_code == 200, form.text
    action = f"/web/expenses/{expense_id}/corrections"
    data = {**_hidden_form(form.text, action), "merchant": "月报更正后的商家", "category": "餐饮", "reason": ""}
    invalid = web_client.post(action, data=data, follow_redirects=False)
    assert invalid.status_code == 422, invalid.text
    assert "请说明这次更正的原因" in invalid.text
    assert "月报更正后的商家" in invalid.text
    retained = _hidden_form(invalid.text, action)
    assert {key: retained[key] for key in origin} == origin
    assert retained["ledger_id"] == "owner"

    assert retained["idempotency_key"] == data["idempotency_key"]
    assert retained["expected_row_version"] == data["expected_row_version"]
    _intervening_correction(web_client, identity, expense_id)
    data.update(retained)
    data["reason"] = "对照原月报核准商家"
    conflict = web_client.post(action, data=data, follow_redirects=False)
    assert conflict.status_code == 409, conflict.text
    retained = _hidden_form(conflict.text, action)
    assert {key: retained[key] for key in origin} == origin
    assert retained["ledger_id"] == "owner"
    assert "另一端更正商家" in conflict.text
    data.update(retained)
    data["merchant"] = "月报更正后的商家"
    success = web_client.post(action, data=data, follow_redirects=False)
    assert success.status_code == 303, success.text
    _assert_query(success.headers["location"], fact_path, ledger_id="owner",
                  **origin)
    result = web_client.get(success.headers["location"])
    assert result.status_code == 200, result.text
    assert "月报更正后的商家" in result.text
    stored = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert stored.status_code == 200, stored.text
    assert stored.json()["merchant"] == "月报更正后的商家"
    return_anchor = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*>\s*返回原月份月报\s*</a>', result.text)
    assert return_anchor is not None
    return_link = unescape(return_anchor.group(1))
    _assert_query(return_link, "/web/reports", ledger_id="owner", **report_task)
    returned = web_client.get(return_link)
    assert returned.status_code == 200, returned.text
    assert "月报更正后的商家" in returned.text


def test_missing_category_viewer_can_read_but_cannot_batch_correct(web_client: TestClient, *, identity) -> None:
    expense_id = create_confirmed(web_client, identity=identity)
    _mark_uncategorized([expense_id])
    writer_page = web_client.get("/web/confirmed?ledger_id=owner&filter=missing_category")
    assert writer_page.status_code == 200, writer_page.text
    action = "/web/confirmed/batch-update"
    data = {**_hidden_form(writer_page.text, action),
            **bulk_snapshot_fields(web_client, [expense_id], identity=identity),
            "action": "set_category", "category": "交通", "reason": "只读角色不能补分类"}
    member_id = owner_member_id()
    with SessionLocal() as db:
        member = db.get(LedgerMember, member_id)
        assert member is not None
        member.role = "viewer"
        db.commit()

    page = web_client.get("/web/confirmed?ledger_id=owner&filter=missing_category")
    assert page.status_code == 200, page.text
    hrefs = _row_hrefs(page.text)
    assert len(hrefs) == 1
    assert f'action="{action}"' not in page.text
    detail = web_client.get(hrefs[0])
    assert detail.status_code == 200, detail.text
    assert not any(urlsplit(link["href"]).path.endswith("/correct") for link in _anchors(detail.text))
    denied = web_client.post(action, data=data, follow_redirects=False)
    assert denied.status_code == 403, denied.text
    assert _quality(web_client, identity)["missing_category_confirmed"] == 1
    with SessionLocal() as db:
        stored = db.get(Expense, expense_id)
        assert stored is not None and stored.category == ""
