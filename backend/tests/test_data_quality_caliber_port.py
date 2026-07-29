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

from urllib.parse import unquote

from _web_bulk_test_support import bulk_snapshot_fields as _bulk_snapshot_fields
from api_contract_helpers import patch_expense
from fastapi.testclient import TestClient
from sqlalchemy import select
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


def test_web_bulk_confirm_ready_applies_full_ready_caliber(web_client: TestClient, *, identity) -> None:
    """PR #230 round 7: /web/review/bulk confirm_ready must skip every row the
    ready filter would hide — not just missing-amount rows — with per-dimension
    skip reasons (the pre-fix behavior confirmed none/null-category and
    merchant-noise rows outright)."""
    with SessionLocal() as db:
        ready = Expense(
            tenant_id="owner", amount_cents=100, merchant="星巴克", category="餐饮",
            source="pytest", status="pending", duplicate_status="none",
        )
        no_amount = Expense(
            tenant_id="owner", amount_cents=None, merchant="麦当劳", category="餐饮",
            source="pytest", status="pending", duplicate_status="none",
        )
        noise_merchant = Expense(
            tenant_id="owner", amount_cents=300, merchant="12:34", category="餐饮",
            source="pytest", status="pending", duplicate_status="none",
        )
        token_category = Expense(
            tenant_id="owner", amount_cents=400, merchant="肯德基", category="none",
            source="pytest", status="pending", duplicate_status="none",
        )
        suspected = Expense(
            tenant_id="owner", amount_cents=500, merchant="汉堡王", category="餐饮",
            source="pytest", status="pending", duplicate_status="suspected",
        )
        fx_blocked = Expense(
            tenant_id="owner", amount_cents=600, merchant="必胜客", category="餐饮",
            source="pytest", status="pending", duplicate_status="none",
            fx_status=FX_STATUS_PENDING,
        )
        db.add_all([ready, no_amount, noise_merchant, token_category, suspected, fx_blocked])
        db.commit()
        ids = {
            "ready": ready.id, "no_amount": no_amount.id, "noise": noise_merchant.id,
            "token": token_category.id, "suspected": suspected.id, "fx": fx_blocked.id,
        }
    resp = web_client.post(
        "/web/review/bulk",
        data={
            "action": "confirm_ready",
            "ledger_id": "owner",
            **_bulk_snapshot_fields(web_client, list(ids.values()), identity=identity),
            "filter": "all",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    message = unquote(resp.headers["location"])
    for reason in ("缺金额", "缺商家", "缺分类", "疑似重复待裁决", "待汇率就绪"):
        assert reason in message, f"skip reason missing from bulk message: {reason}"

    with SessionLocal() as db:
        states = {
            row.id: row.status
            for row in db.scalars(select(Expense).where(Expense.id.in_(ids.values())))
        }
    assert states[ids["ready"]] == "confirmed"
    for key in ("no_amount", "noise", "token", "suspected", "fx"):
        assert states[ids[key]] == "pending", f"row must stay pending: {key}"


def test_update_expense_folds_dirty_category_tokens(client: TestClient, *, identity) -> None:
    """PR #230 round 7: an explicit category write carrying a dirty legacy
    token must not persist — the write path folds it to 「其他」 (valid writes
    pass through untouched)."""
    with SessionLocal() as db:
        row = Expense(
            tenant_id="owner", amount_cents=100, merchant="星巴克", category="餐饮",
            source="pytest", status="pending", duplicate_status="none",
        )
        db.add(row)
        db.commit()
        expense_id = row.id

    for token in ("none", "未分類", "Null"):
        response = patch_expense(
            client, expense_id, headers=identity.app_headers, fields={"category": token}
        )
        assert response.status_code == 200, response.text
        with SessionLocal() as db:
            stored = db.get(Expense, expense_id)
            assert stored is not None
            assert stored.category == "其他", f"dirty token must fold to 其他: {token}"

    response = patch_expense(
        client, expense_id, headers=identity.app_headers, fields={"category": "交通"}
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        stored = db.get(Expense, expense_id)
        assert stored is not None
        assert stored.category == "交通"


def test_web_pending_row_surfaces_missing_category_and_suppresses_ready_pill(
    web_client: TestClient, *, identity,
) -> None:
    """PR #230 round 12: a none/null-category row must show the 缺分类 signal
    (same family as 缺金额/缺商家), never the green 可确认 pill, and must not
    render the raw token as plain category text. fx-pending rows likewise get
    待汇率 instead of 可确认 — the row pills now mirror the ready filter."""
    with SessionLocal() as db:
        dirty = Expense(
            tenant_id="owner", amount_cents=100, merchant="星巴克", category="none",
            source="pytest", status="pending", duplicate_status="none",
        )
        ready = Expense(
            tenant_id="owner", amount_cents=200, merchant="麦当劳", category="餐饮",
            source="pytest", status="pending", duplicate_status="none",
        )
        fx_blocked = Expense(
            tenant_id="owner", amount_cents=300, merchant="肯德基", category="餐饮",
            source="pytest", status="pending", duplicate_status="none",
            fx_status=FX_STATUS_PENDING,
        )
        db.add_all([dirty, ready, fx_blocked])
        db.commit()

    resp = web_client.get("/web/pending?ledger_id=owner")
    assert resp.status_code == 200
    assert "缺分类" in resp.text
    assert "待汇率" in resp.text
    # Only the genuinely ready row gets the green pill (218-D S4: product-status 族)。
    assert resp.text.count('class="product-status product-status--success"') == 1
    # The dirty row's cell shows the missing marker, not the raw token.
    assert 'exp-cat exp-cat-missing">待分类</span>' in resp.text
    assert 'exp-cat">none</span>' not in resp.text
