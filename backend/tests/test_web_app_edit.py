"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re

import pytest
from api_contract_helpers import web_confirm_expense, web_save_expense
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.models import Expense


def _create_pending(client: TestClient, *, identity) -> int:
    """Helper: upload a tiny PNG to the owner ledger so /web/pending sees it."""
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def test_web_edit_save_updates_amount(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    pending = web_client.get("/web/pending?ledger_id=owner&filter=missing_amount")
    assert (
        f'src="/web/expenses/{expense_id}/thumbnail?ledger_id=owner"'
        in pending.text
    )
    assert 'data-receipt-thumb' in pending.text
    receipt_js = web_client.get("/static/web/desktop/receipt-skeletons.js")
    assert receipt_js.status_code == 200
    assert 'box.classList.add("is-failed")' in receipt_js.text
    assert 'label.textContent = "加载失败"' in receipt_js.text

    inbox_css = web_client.get("/static/web/product/domains/inbox.css")
    assert inbox_css.status_code == 200
    assert ".exp-thumb-receipt.is-loaded .exp-thumb-label" in inbox_css.text
    assert ".exp-thumb-receipt .exp-thumb-label {" not in inbox_css.text
    assert "grid-area: 1 / 1" in inbox_css.text
    assert (
        f"/web/expenses/{expense_id}/edit?ledger_id=owner"
        "&return_to=pending&return_filter=missing_amount"
        in pending.text
    )
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "12.34", "merchant": "测试商家", "category": "餐饮",
              "note": "", "ledger_id": "owner", "return_to": "pending",
              "return_filter": "missing_amount"},
    )
    assert resp.status_code in {303, 307}
    assert (
        resp.headers["location"]
        == "/web/pending?ledger_id=owner&filter=missing_amount"
    )
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert detail.status_code == 200
    assert "12.34" in detail.text
    assert "测试商家" in detail.text
    row_version = re.search(
        r'name="expected_row_version" value="([^"]+)"',
        detail.text,
    )
    assert row_version is not None
    confirmed = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={
            "ledger_id": "owner",
            "expected_row_version": row_version.group(1),
            "return_filter": "ready",
        },
        follow_redirects=False,
    )
    assert confirmed.status_code == 303
    assert confirmed.headers["location"] == "/web/pending?ledger_id=owner&filter=ready"


def test_web_edit_save_preserves_foreign_currency_fields(web_client: TestClient, *, identity) -> None:
    rate = web_client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={"currency_code": "USD", "rate_date": "2026-05-04", "rate_to_cny": "7.0000"},
    )
    assert rate.status_code == 200, rate.json()
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 12345,
            "merchant": "Foreign Cafe",
            "category": "餐饮",
            "expense_time": "2026-05-04T12:00:00Z",
        },
    )
    assert created.status_code == 200, created.json()
    expense_id = int(created.json()["id"])

    saved = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={
            "ledger_id": "owner",
            "original_currency": "USD",
            "amount_yuan": "124.00",
            "merchant": "Foreign Cafe Updated",
            "category": "餐饮",
            "note": "kept as USD",
        },
    )
    assert saved.status_code in {303, 307}, saved.text

    detail = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    payload = detail.json()
    assert payload["original_currency_code"] == "USD"
    assert payload["original_amount_minor"] == 12400
    assert payload["amount_cents"] == 86800
    assert payload["merchant"] == "Foreign Cafe Updated"


def test_web_edit_save_sets_expense_time_in_accounting_tz(
    web_client: TestClient, *, identity
) -> None:
    """批1: the datetime-local input is a Beijing wall-clock the route must
    assume-local → store UTC. 20:00 Asia/Shanghai = 12:00Z. The edit page then
    prefills the same 20:00 wall-clock (round-trip, no 8h drift)."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "12.34", "merchant": "夜宵店", "category": "餐饮",
              "note": "", "ledger_id": "owner", "expense_time": "2026-05-04T20:00"},
    )
    assert resp.status_code in {303, 307}, resp.text

    payload = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    ).json()
    # 20:00 +08:00 stored as 12:00Z (storage stays UTC).
    assert payload["expense_time"] == "2026-05-04T12:00:00Z", payload["expense_time"]

    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert detail.status_code == 200
    # Prefilled back into the datetime-local input as the Beijing wall-clock.
    assert 'name="expense_time"' in detail.text
    assert 'value="2026-05-04T20:00"' in detail.text


def test_web_edit_save_bad_expense_time_shows_error(
    web_client: TestClient, *, identity
) -> None:
    """An unparseable time flashes the edit error and leaves the row untouched."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "9.00", "merchant": "店", "category": "餐饮",
              "note": "", "ledger_id": "owner", "expense_time": "not-a-time"},
    )
    assert resp.status_code == 200
    assert "请填写正确的时间" in resp.text
    # Nothing committed: a fresh pending still has no expense_time and no amount.
    payload = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    ).json()
    assert payload["expense_time"] is None
    assert payload["amount_cents"] is None


def test_web_edit_save_sets_and_clears_tags(web_client: TestClient, *, identity) -> None:
    """批1: tags save normalises the comma list; a blank tags field clears them
    (mirrors PATCH /api/expenses — "" clears, omitted leaves untouched)."""
    expense_id = _create_pending(web_client, identity=identity)
    saved = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "5.00", "merchant": "店", "category": "餐饮",
              "note": "", "ledger_id": "owner", "tags": "报销, 出差"},
    )
    assert saved.status_code in {303, 307}, saved.text
    payload = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    ).json()
    assert payload["tags"] == "报销, 出差", payload["tags"]
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert 'name="tags"' in detail.text
    assert "报销, 出差" in detail.text

    # Blank tags field clears them.
    cleared = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "5.00", "merchant": "店", "category": "餐饮",
              "note": "", "ledger_id": "owner", "tags": ""},
    )
    assert cleared.status_code in {303, 307}, cleared.text
    after = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    ).json()
    assert after["tags"] is None, after["tags"]


def test_web_edit_renders_category_datalist_with_used_category(
    web_client: TestClient, *, identity
) -> None:
    """批1: the 分类 input carries a <datalist> seeded with the ledger's used
    categories ∪ defaults, so spelling drift is curbed at the input."""
    expense_id = _create_pending(web_client, identity=identity)
    saved = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "5.00", "merchant": "店", "category": "测试专属分类",
              "note": "", "ledger_id": "owner"},
    )
    assert saved.status_code in {303, 307}, saved.text

    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert detail.status_code == 200
    assert f'for="expense-{expense_id}-amount-yuan"' in detail.text
    assert f'id="expense-{expense_id}-amount-yuan"' in detail.text
    assert 'list="category-options"' in detail.text
    assert '<datalist id="category-options">' in detail.text
    assert '<option value="测试专属分类">' in detail.text  # the ledger's own
    assert '<option value="餐饮">' in detail.text  # a default

    drawer = web_client.get(
        f"/web/expenses/{expense_id}/edit?ledger_id=owner&fragment=1"
    )
    assert drawer.status_code == 200
    assert f'for="drawer-expense-{expense_id}-amount-yuan"' in drawer.text
    assert f'id="drawer-expense-{expense_id}-amount-yuan"' in drawer.text
    assert 'list="category-options-drawer"' in drawer.text
    assert 'name="expense_time"' in drawer.text
    assert 'name="tags"' in drawer.text
    assert 'class="product-drawer-editor"' in drawer.text
    assert 'name="csrf_token"' in drawer.text
    assert 'name="expected_row_version"' in drawer.text
    assert "收件 / 待我处理 /" in drawer.text
    assert "dt-card" not in drawer.text
    assert 'class="dt-' not in drawer.text
    assert 'style="' not in drawer.text
    assert "⚠" not in drawer.text


def test_web_edit_image_uses_skeleton_placeholder(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert detail.status_code == 200
    assert "data-image-skeleton" in detail.text
    assert "receipt-loading" in detail.text
    assert "receipt-image-skeleton" not in detail.text

    drawer = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&fragment=1")
    assert drawer.status_code == 200
    assert "data-image-skeleton" in drawer.text
    assert "receipt-image-skeleton" in drawer.text


def test_web_save_invalid_amount_shows_error(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "not-a-number", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner"},
    )
    assert resp.status_code == 200
    assert "金额不是合法金额" in resp.text


def test_web_confirm_without_amount_shows_chinese_error(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_confirm_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )
    assert resp.status_code == 200
    assert "请先填写金额" in resp.text


@pytest.mark.parametrize(
    "input_str,expected_cents",
    [
        ("12.34", 1234),
        ("0.01", 1),
        ("0.1", 10),
        ("100", 10000),
        ("0", 0),
    ],
)
def test_web_amount_decimal_precision(
    web_client: TestClient, input_str: str, expected_cents: int
, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": input_str, "merchant": "", "category": "", "note": "",
              "ledger_id": "owner"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    from decimal import Decimal
    expected_display = str((Decimal(expected_cents) / Decimal("100")).quantize(Decimal("0.01")))
    assert expected_display in detail.text


@pytest.mark.parametrize(
    ("currency_code", "valid_input", "invalid_input", "expected_minor"),
    [
        pytest.param("CNY", "12.34", "12.345", 1234, id="cny-two-fraction"),
        pytest.param("JPY", "1234", "1.5", 1234, id="jpy-zero-fraction"),
        pytest.param("KRW", "1234", "1.5", 1234, id="krw-zero-fraction"),
    ],
)
def test_web_amount_edit_rejects_precision_beyond_frozen_currency(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
    currency_code: str,
    valid_input: str,
    invalid_input: str,
    expected_minor: int,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", currency_code)
    get_settings.cache_clear()
    try:
        expense_id = _create_pending(web_client, identity=identity)
        with SessionLocal() as db:
            expense = db.get(Expense, expense_id)
            assert expense is not None
            assert expense.home_currency_code == currency_code
            assert expense.original_currency_code == currency_code
            assert expense.amount_cents is None
            assert expense.original_amount_minor is None
        saved = web_save_expense(
            web_client,
            expense_id,
            identity=identity,
            data={
                "amount_yuan": valid_input,
                "original_currency": currency_code,
                "merchant": "",
                "category": "",
                "note": "",
                "ledger_id": "owner",
            },
        )
        assert saved.status_code in {303, 307}, saved.text
        with SessionLocal() as db:
            expense = db.get(Expense, expense_id)
            assert expense is not None
            assert expense.home_currency_code == currency_code
            assert expense.original_currency_code == currency_code
            assert expense.amount_cents == expected_minor
            before = (
                expense.amount_cents,
                expense.original_amount_minor,
                expense.row_version,
            )

        rejected = web_save_expense(
            web_client,
            expense_id,
            identity=identity,
            data={
                "amount_yuan": invalid_input,
                "original_currency": currency_code,
                "merchant": "",
                "category": "",
                "note": "",
                "ledger_id": "owner",
            },
            follow_redirects=True,
        )
        assert rejected.status_code == 200
        assert currency_code in rejected.text
        with SessionLocal() as db:
            expense = db.get(Expense, expense_id)
            assert expense is not None
            after = (
                expense.amount_cents,
                expense.original_amount_minor,
                expense.row_version,
            )
        assert after == before
    finally:
        get_settings.cache_clear()


def test_web_save_negative_amount_shows_error(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "-5.00", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner"},
    )
    assert resp.status_code == 200
    assert "负数" in resp.text


def test_web_edit_drawer_default_submit_is_save_not_reject(
    web_client: TestClient, *, identity
) -> None:
    """隐式提交守卫:抽屉表单 tree-order 首个 submit 必须是无 formaction 的
    shim(Enter=保存),且所有 /reject formaction 按钮带 data-confirm。没有
    shim 时首个可见 submit 是「忽略草稿」——在输入框按 Enter 直接软删。
    同一回归面也固定模态抽屉的 Tab 闭环、背景 inert 与焦点恢复。"""
    import re

    expense_id = _create_pending(web_client, identity=identity)
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert pending.status_code == 200
    assert 'id="drawer-scrim" aria-hidden="true"' in pending.text
    assert re.search(
        r'<aside class="drawer".*?aria-modal="true".*?aria-hidden="true"',
        pending.text,
        re.S,
    )

    drawer = web_client.get(
        f"/web/expenses/{expense_id}/edit?ledger_id=owner&fragment=1"
    )
    assert drawer.status_code == 200

    buttons = re.findall(r'<button\b[^>]*type="submit"[^>]*>', drawer.text)
    assert buttons, drawer.text
    assert "formaction" not in buttons[0]
    reject_buttons = [b for b in buttons if "/reject" in b]
    assert reject_buttons
    for btn in reject_buttons:
        assert "data-confirm" in btn

    drawer_js = web_client.get("/static/web/desktop/drawer.js")
    assert drawer_js.status_code == 200
    assert "restoreFocusTo" in drawer_js.text
    assert "focusDrawer()" in drawer_js.text
    assert 'e.key === "Tab"' in drawer_js.text
    assert "event.shiftKey" in drawer_js.text
    assert "last.focus({ preventScroll: true })" in drawer_js.text
    assert "first.focus({ preventScroll: true })" in drawer_js.text
    assert 'document.querySelectorAll("dialog[open]")' in drawer_js.text
    assert 'element.setAttribute("inert", "")' in drawer_js.text
    assert 'state.element.removeAttribute("inert")' in drawer_js.text
    assert "while (branch && branch !== document.body)" in drawer_js.text
    assert 'element.tagName === "DIALOG"' in drawer_js.text
    assert 'drawer.setAttribute("aria-hidden", "false")' in drawer_js.text
    assert drawer_js.text.index("unlockBackground();") < drawer_js.text.index(
        "restoreFocus();"
    )
