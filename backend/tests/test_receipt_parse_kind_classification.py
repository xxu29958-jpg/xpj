"""ADR-0035 PR-2: receipt parser identifies discount / tax / service_fee
line items via Chinese keyword pattern.

Focuses on line-level classification only; whole-receipt parsing flow is
covered by test_receipt_parse_scoring.py + smoke_test.py.
"""

from __future__ import annotations

from app.services.receipt_parse_service import (
    _classify_item_kind,
    _parse_receipt_item_line,
)

# --- _classify_item_kind --------------------------------------------------


def test_classify_discount_keyword() -> None:
    assert _classify_item_kind("VIP 优惠 -3.00") == "discount"
    assert _classify_item_kind("满100减10 -10.00") == "discount"
    assert _classify_item_kind("立减 ¥3.00") == "discount"
    assert _classify_item_kind("折扣 -2.50") == "discount"
    assert _classify_item_kind("红包抵扣 -5.00") == "discount"


def test_classify_tax_keyword() -> None:
    assert _classify_item_kind("VAT 税额 0.96") == "tax"
    assert _classify_item_kind("增值税 5.00") == "tax"
    assert _classify_item_kind("GST 1.20") == "tax"


def test_classify_service_fee_keyword() -> None:
    assert _classify_item_kind("服务费 10.00") == "service_fee"
    assert _classify_item_kind("茶位费 5.00") == "service_fee"
    assert _classify_item_kind("配送费 3.00") == "service_fee"


def test_classify_defaults_to_product() -> None:
    assert _classify_item_kind("拿铁 1杯 5.00") == "product"
    assert _classify_item_kind("苹果 2斤 18.00") == "product"


# --- _parse_receipt_item_line sign normalization --------------------------


def test_discount_line_negative_amount_passthrough() -> None:
    """OCR outputs '-3.00' for discount; parser keeps negative."""
    item = _parse_receipt_item_line("VIP优惠 -3.00")
    assert item is not None
    assert item.kind == "discount"
    assert item.amount_cents == -300


def test_discount_line_positive_amount_flipped() -> None:
    """OCR outputs positive amount but row is semantically discount;
    parser normalizes sign per ADR-0035."""
    item = _parse_receipt_item_line("立减 3.00")
    assert item is not None
    assert item.kind == "discount"
    assert item.amount_cents == -300


def test_discount_zero_amount_rejected() -> None:
    """abs(0) = 0; no meaningful discount."""
    assert _parse_receipt_item_line("优惠 0.00") is None


def test_tax_line_keeps_positive_amount() -> None:
    item = _parse_receipt_item_line("VAT税额 0.96")
    assert item is not None
    assert item.kind == "tax"
    assert item.amount_cents == 96


def test_service_fee_line_keeps_positive_amount() -> None:
    item = _parse_receipt_item_line("服务费 10.00")
    assert item is not None
    assert item.kind == "service_fee"
    assert item.amount_cents == 1000


def test_product_line_negative_amount_rejected() -> None:
    """Plain product line with negative amount is broken OCR output;
    parser rejects to avoid CHECK constraint violation downstream."""
    assert _parse_receipt_item_line("苹果 2斤 -18.00") is None


def test_product_line_normal() -> None:
    item = _parse_receipt_item_line("拿铁 1杯 5.00")
    assert item is not None
    assert item.kind == "product"
    assert item.amount_cents == 500


# --- discount / tax / service_fee: no unit price + no category ------------


def test_non_product_kinds_suppress_unit_price_and_category() -> None:
    """Discount / tax / service_fee 行 unit_price 没意义；category 应保
    NULL 避免 UI 渲染"优惠 类别=餐饮"这种 nonsense."""
    discount = _parse_receipt_item_line("VIP优惠 -3.00")
    assert discount is not None
    assert discount.unit_price_cents is None
    assert discount.category is None

    tax = _parse_receipt_item_line("VAT税额 0.96")
    assert tax is not None
    assert tax.unit_price_cents is None
    assert tax.category is None
