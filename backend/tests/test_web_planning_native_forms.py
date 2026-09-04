"""Native Planning forms must reach existing Owners with their rendered scope/tokens."""

import pytest
from _web_native_form_support import hidden_post_forms
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize(
    ("route", "fields", "query", "amount_field", "amount_minor"),
    [
        (
            "/web/goals",
            {"name": "原生目标", "target_amount_yuan": "1500.50", "category": "餐饮"},
            "/api/goals?month=2026-05",
            "target_amount_cents",
            150050,
        ),
        (
            "/web/recurring",
            {"merchant": "原生固定支出", "baseline_amount_yuan": "18.25", "next_expected_date": "2026-06-04"},
            "/api/recurring/items",
            "baseline_amount_cents",
            1825,
        ),
        (
            "/web/income-plans",
            {
                "label": "原生收入", "source_type": "salary", "frequency": "one_time",
                "income_month_year": "2026", "income_month_number": "5",
                "amount_yuan": "1200.25", "pay_day": "3",
            },
            "/api/income-plans",
            "amount_cents",
            120025,
        ),
    ],
)
def test_native_create_preserves_selected_ledger_and_money(
    web_client, identity, route, fields, query, amount_field, amount_minor,
) -> None:
    # The real loopback peer executes CSRF checks; the usual 'testclient' peer skips them.
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 53005)) as browser:
        page = browser.get(f"{route}?ledger_id=tester_1&month=2026-05")
        assert page.status_code == 200
        action = f"{route}/create"
        submitted = browser.post(
            action,
            data={**hidden_post_forms(page.text)[action], **fields},
            headers={"Origin": "http://127.0.0.1", "Referer": str(page.url)},
            follow_redirects=False,
        )
        assert submitted.status_code == 303, submitted.text
        selected = browser.get(query, headers=identity.gray_app_headers)
        assert selected.status_code == 200
        rows = selected.json()["items"]
        assert len(rows) == 1
        assert rows[0][amount_field] == amount_minor
        default = browser.get(query, headers=identity.app_headers)
        assert default.status_code == 200
        assert default.json()["items"] == []


def test_native_income_archive_and_restore_preserve_scope_and_occ(web_client, identity) -> None:
    created = web_client.post(
        "/api/income-plans", headers=identity.gray_app_headers,
        json={"label": "生命周期收入", "source_type": "bonus", "amount_cents": 68000, "pay_day": 1},
    )
    assert created.status_code == 201, created.text
    public_id = created.json()["public_id"]
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 53006)) as browser:
        for command, expected_status in (("archive", "archived"), ("restore", "active")):
            page = browser.get("/web/income-plans?ledger_id=tester_1")
            assert page.status_code == 200
            action = f"/web/income-plans/{public_id}/{command}"
            saved = browser.post(
                action, data=hidden_post_forms(page.text)[action],
                headers={"Origin": "http://127.0.0.1", "Referer": str(page.url)},
                follow_redirects=False,
            )
            assert saved.status_code == 303, saved.text
            result = browser.get("/api/income-plans?status=all", headers=identity.gray_app_headers)
            assert result.status_code == 200
            row = next(item for item in result.json()["items"] if item["public_id"] == public_id)
            assert row["status"] == expected_status
            assert row["amount_cents"] == 68000
            assert row["row_version"] > created.json()["row_version"]
