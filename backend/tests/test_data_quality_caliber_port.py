"""PR #230 review round 3 — pin the Android↔backend caliber port.

The merchant-usability and category-token rules in
``app.services.data_quality_service`` are line-for-line ports of Android
``PendingScreenModels.kt`` (pendingMerchantPresentation) and
``DefaultCategories.kt`` (isUncategorizedExpenseCategory). Both sides run
the SAME sample sets — the Android twins live in
``PendingScreenModelsTest.kt`` / ``DefaultCategoriesTest.kt``; any drift
must redden one of them.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.fx_constants import FX_STATUS_PENDING
from app.models import Expense
from app.services.data_quality_service import (
    is_uncategorized_expense_category,
    is_usable_pending_merchant,
)

# Keep in sync with PendingScreenModelsTest.merchantUsabilitySharedSamples.
UNUSABLE_MERCHANT_SAMPLES = [
    None,
    "",
    "   ",
    "A",  # single letter: < 2 meaningful chars
    "12",  # digits only: no letter
    "12:34",
    "3:15 PM",
    "12:30:45",
    "2026-07-17 12:34",
    "2026年7月17日 周五",
    "7月22日",
    "123456",
    "18:04 0",
    "——",
]

USABLE_MERCHANT_SAMPLES = [
    "苏宁",
    "7-Eleven",
    "3M",
    "85度C",
    "星巴克咖啡",
    "A1",
    "ab",
    " 星巴克咖啡 ",
]

# Keep in sync with DefaultCategoriesTest.uncategorizedTokenSharedSamples.
UNCATEGORIZED_SAMPLES = [
    None,
    "",
    "  ",
    "未分类",
    " 未分类 ",
    "未分類",
    "none",
    "None",
    "NONE",
    "nOnE",
    "null",
    "NULL",
    "Null",
    " none ",
    "\tnull\t",
]

CATEGORIZED_SAMPLES = ["其他", "餐饮", "nonee", "nullable", "未分类x"]


def test_merchant_usability_shared_samples() -> None:
    for sample in UNUSABLE_MERCHANT_SAMPLES:
        assert not is_usable_pending_merchant(sample), f"must be unusable: {sample!r}"
    for sample in USABLE_MERCHANT_SAMPLES:
        assert is_usable_pending_merchant(sample), f"must be usable: {sample!r}"


def test_uncategorized_token_shared_samples() -> None:
    for sample in UNCATEGORIZED_SAMPLES:
        assert is_uncategorized_expense_category(sample), f"must be uncategorized: {sample!r}"
    for sample in CATEGORIZED_SAMPLES:
        assert not is_uncategorized_expense_category(sample), f"must be categorized: {sample!r}"


def _insert_pending(db: Session, **overrides) -> None:
    defaults = {
        "tenant_id": "owner",
        "amount_cents": 1000,
        "merchant": "星巴克",
        "category": "餐饮",
        "source": "pytest",
        "status": "pending",
        "duplicate_status": "none",
    }
    defaults.update(overrides)
    db.add(Expense(**defaults))


def test_noise_merchants_count_as_missing_and_never_as_ready(
    client: TestClient, *, identity,
) -> None:
    with SessionLocal() as db:
        _insert_pending(db, merchant=None, category="餐饮")
        _insert_pending(db, merchant="12:34", category="餐饮")
        _insert_pending(db, merchant="A", category="餐饮")
        _insert_pending(db, merchant="星巴克", category="餐饮")
        db.commit()

    response = client.get("/api/insights/data-quality", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pending_total"] == 4
    # null + OCR time noise + single letter all miss a usable merchant.
    assert body["missing_merchant"] == 3
    # Only 星巴克 is ready; noise merchants never enter the ready calibers.
    assert body["ready_to_confirm"] == 1
    assert body["ready_to_confirm_categorized"] == 1


def test_none_null_category_tokens_count_as_uncategorized(
    client: TestClient, *, identity,
) -> None:
    with SessionLocal() as db:
        _insert_pending(db, category="none")
        _insert_pending(db, category="Null")
        _insert_pending(db, category="餐饮")
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=500,
                merchant="星巴克",
                category="NONE",
                source="pytest",
                status="confirmed",
                duplicate_status="none",
            )
        )
        db.commit()

    response = client.get("/api/insights/data-quality", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["missing_category"] == 3
    assert body["missing_category_pending"] == 2
    assert body["missing_category_confirmed"] == 1
    # All three pending rows are merchant-usable with amount; only 餐饮 is
    # ready-categorized — 'none'/'Null' rows drop out of that caliber.
    assert body["ready_to_confirm"] == 3
    assert body["ready_to_confirm_categorized"] == 1


def test_web_ready_caliber_covers_fx_and_shared_category_tokens(
    web_client: TestClient, *, identity,
) -> None:
    """PR #230 round 6: the web ready filter/tab count and the DQ page's ready
    number share the ready_to_confirm_categorized caliber — fx-pending rows
    (the confirm path 409s them) and uncategorized-token rows drop out."""
    with SessionLocal() as db:
        ready = Expense(
            tenant_id="owner", amount_cents=100, merchant="星巴克", category="餐饮",
            source="pytest", status="pending", duplicate_status="none",
        )
        fx_blocked = Expense(
            tenant_id="owner", amount_cents=200, merchant="麦当劳", category="餐饮",
            source="pytest", status="pending", duplicate_status="none",
            fx_status=FX_STATUS_PENDING,
        )
        token_blocked = Expense(
            tenant_id="owner", amount_cents=300, merchant="肯德基", category="none",
            source="pytest", status="pending", duplicate_status="none",
        )
        db.add_all([ready, fx_blocked, token_blocked])
        db.commit()
        ready_id, fx_id, token_id = ready.id, fx_blocked.id, token_blocked.id

    resp = web_client.get("/web/pending?ledger_id=owner&filter=ready")
    assert resp.status_code == 200
    assert f"/web/expenses/{ready_id}/edit" in resp.text
    assert f"/web/expenses/{fx_id}/edit" not in resp.text
    assert f"/web/expenses/{token_id}/edit" not in resp.text

    resp = web_client.get("/web/pending?ledger_id=owner&filter=missing_category")
    assert resp.status_code == 200
    assert f"/web/expenses/{token_id}/edit" in resp.text

    # The DQ page advertises exactly what the ready link lands on (categorized
    # caliber) — not the wider ready_to_confirm aggregate.
    resp = web_client.get("/web/data-quality?ledger_id=owner")
    assert resp.status_code == 200
    assert "1 条可批量确认" in resp.text
