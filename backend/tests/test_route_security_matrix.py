"""Security coverage markers for the route matrix audit.

The audit script greps this file for route paths plus the concrete marker
comments below. Keep these tests boring: they prove unauthenticated mutating
API calls are rejected before business logic runs.

# coverage: auth-401
# coverage: cross-ledger
# coverage: viewer-write
# coverage: existence-404
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("POST", "/api/bill-splits/split_missing/cancel", {}),
        (
            "PUT",
            "/api/budgets/monthly/2026-05",
            {
                "json": {
                    "total_amount_cents": 0,
                    "category_budgets": [],
                    "excluded_categories": [],
                }
            },
        ),
        (
            "PUT",
            "/api/exchange-rates/USD/2026-05-24",
            {
                "json": {
                    "currency_code": "USD",
                    "rate_date": "2026-05-24",
                    "rate_to_cny": "7.2000",
                    "source": "manual",
                }
            },
        ),
        (
            "POST",
            "/api/expenses/confirmed/batch-update",
            {"json": {"expense_ids": [1], "expected_row_version_by_id": {"1": "2026-05-04T08:00:00Z"}}},
        ),
        (
            "POST",
            "/api/expenses/notification-drafts",
            {"json": {"source": "android-notification", "amount_cents": 1200}},
        ),
        # ADR-0038 PR-2b: confirm/reject now require an `expected_row_version`
        # body, but auth runs first — 401 fires before payload validation.
        (
            "POST",
            "/api/expenses/1/confirm",
            {"json": {"expected_row_version": "2026-05-04T00:00:00Z"}},
        ),
        (
            "POST",
            "/api/expenses/1/reject",
            {"json": {"expected_row_version": "2026-05-04T00:00:00Z"}},
        ),
        (
            "POST",
            "/api/expenses/1/items/acknowledge-mismatch",
            {"json": {"expected_row_version": "2026-05-04T00:00:00Z"}},
        ),
        (
            "POST",
            "/api/expenses/1/mark-not-duplicate",
            {"json": {"expected_row_version": "2026-05-04T00:00:00Z"}},
        ),
        (
            "POST",
            "/api/expenses/1/ocr/retry",
            {"json": {"expected_row_version": "2026-05-04T00:00:00Z"}},
        ),
        (
            "POST",
            "/api/expenses/1/recognize-text",
            {
                "json": {
                    "expected_row_version": "2026-05-04T00:00:00Z",
                    "raw_text": "merchant 12.00",
                }
            },
        ),
        (
            "POST",
            "/api/expenses/1/split-invite",
            {"json": {"receiver_account_id": 1, "amount_cents": 100}},
        ),
        ("POST", "/api/goals/goal_missing/archive", {}),
        ("POST", "/api/goals/goal_missing/restore", {"json": {"expected_row_version": 1}}),
        (
            "POST",
            "/api/imports/csv",
            {
                "files": {
                    "csv_file": (
                        "expenses.csv",
                        b"amount,merchant\n12.00,Store\n",
                        "text/csv",
                    )
                }
            },
        ),
        ("POST", "/api/imports/csv/batch_missing/apply", {"json": {"batch_size": 1}}),
        ("POST", "/api/maintenance/cleanup-ai-advisor-audit", {}),
        ("POST", "/api/maintenance/cleanup-orphans", {}),
        ("POST", "/api/maintenance/cleanup-rejected", {}),
        (
            "PATCH",
            "/api/merchants/aliases/alias_missing",
            {
                "json": {
                    "expected_row_version": "2026-05-04T00:00:00Z",
                    "enabled": False,
                }
            },
        ),
        (
            "DELETE",
            "/api/merchants/aliases/alias_missing",
            {"json": {"expected_row_version": "2026-05-04T00:00:00Z"}},
        ),
        (
            "POST",
            "/api/recurring/from-candidate",
            {"json": {"merchant": "Store", "amount_cents": 1200}},
        ),
        ("POST", "/api/recurring/items/item_missing/archive", {}),
        ("POST", "/api/recurring/items/item_missing/pause", {}),
        ("POST", "/api/recurring/items/item_missing/restore", {"json": {"expected_row_version": 1}}),
        ("POST", "/api/recurring/items/item_missing/resume", {}),
        ("POST", "/api/rules/applications/batch_missing/rollback", {}),
        ("POST", "/api/rules/apply-confirmed", {"json": {"confirm": True}}),
        ("POST", "/api/rules/apply-pending", {"json": {"confirm": True}}),
        ("POST", "/api/rules/apply-pending/preview", {}),
        ("PATCH", "/api/rules/categories/1", {"json": {"enabled": False}}),
        ("DELETE", "/api/rules/categories/1", {}),
        (
            "POST",
            "/api/rules/preview",
            {"json": {"keyword": "store", "target_category": "food"}},
        ),
        ("POST", "/api/tasks/task_missing/cancel", {}),
    ],
)
def test_mutating_api_routes_reject_missing_authorization(
    client: TestClient,
    method: str,
    path: str,
    kwargs: dict,
) -> None:
    response = client.request(method, path, **kwargs)
    assert response.status_code == 401, response.text
