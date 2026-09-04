"""Rendered import/review forms must work without client-side token injection."""

from _web_native_form_support import hidden_post_forms
from fastapi.testclient import TestClient

from app.main import app


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
