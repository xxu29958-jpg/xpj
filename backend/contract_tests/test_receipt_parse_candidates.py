"""Conflicting receipt evidence must not silently select the first value."""

import pytest

from app.services.receipt_parse_service import parse_receipt_text


def parse(text, **kwargs):
    return parse_receipt_text(text, currency_code="CNY", minor_unit_exponent=2, **kwargs)


def test_conflicting_paid_amounts_abstain_but_repeated_same_value_keeps_evidence():
    conflict = parse("商家：便利店\n实付金额：20.00\n实付金额：30.00")
    assert conflict.amount_cents is None
    assert next(item for item in conflict.decisions if item.field == "amount_cents").status == "ambiguous"
    assert {item.value for item in conflict.candidates if item.field == "amount_cents"} == {2000, 3000}
    repeated = parse("实付金额：20.00\n实付金额：20.00")
    assert repeated.amount_cents == 2000
    assert len({item.raw_spans for item in repeated.candidates if item.field == "amount_cents"}) == 2


def test_distinct_merchant_labels_are_not_resolved_by_line_order():
    result = parse("商家：第一便利店\n商家：第二便利店\n实付金额：20.00")
    assert result.merchant is None
    assert next(item for item in result.decisions if item.field == "merchant").status == "ambiguous"


def test_spans_refer_to_original_whitespace_and_blocks_are_never_fabricated():
    raw = "\r\n  实付金额：\r\n\r\n 20.00 \r\n 商家：便利店\r\n"
    result = parse(raw, evidence_blocks=[{"text": "different image"}])
    amount = next(item for item in result.candidates if item.field == "amount_cents" and item.source.startswith("label:"))
    start, end = amount.raw_spans[0]
    assert raw[start:end] == "实付金额：\r\n\r\n 20.00"
    assert not amount.block_indices
    categories = [item for item in result.candidates if item.field == "category"]
    assert categories
    assert all("便利店" in raw[start:end] for item in categories for start, end in item.raw_spans)


@pytest.mark.parametrize("raw", [
    "支付失败\n交易金额：25.00元", "退款成功\n退款金额：25.00元",
    "还款成功\n还款金额：25.00元", "收款成功\n收款金额：25.00元",
    "正在付款中...\n支付金额：25.00元",
])
def test_non_expense_or_unfinished_transaction_keeps_evidence_without_filling_expense(raw):
    result = parse(raw)
    assert result.amount_cents is None
    assert any(item.value == 2500 for item in result.candidates if item.field == "amount_cents")
    decision = next(item for item in result.decisions if item.field == "amount_cents")
    assert decision.status == "needs_review" and decision.selected_id is None


def test_amount_roles_bind_to_each_number_before_ranking():
    raw = "支出人民币25.00元，余额125.00元"
    result = parse(raw)
    assert result.amount_cents == 2500
    expense, balance = [item for item in result.candidates if item.field == "amount_cents"]
    assert (expense.value, expense.role) == (2500, "expense")
    assert (balance.value, balance.role) == (12500, "balance")
    assert "125.00" not in "".join(raw[start:end] for start, end in expense.raw_spans)
    conflict = parse("支付金额：25.00元\n交易金额：30.00元")
    assert conflict.amount_cents is None
    assert next(item for item in conflict.decisions if item.field == "amount_cents").status == "ambiguous"


@pytest.mark.parametrize("raw", ["支付成功\n实付金额：1.234元", "支付成功\n￥1.234", "支付成功\n1.2.3元"])
def test_invalid_money_is_not_shortened_to_a_different_valid_amount(raw):
    assert parse(raw).amount_cents is None


@pytest.mark.parametrize("text,code,exponent,minor", [
    ("实付金额：1.234", "KWD", 3, 1234),
    ("支付金额：JPY 2850", "JPY", 0, 2850),
    ("实付金额：KWD 1.234", "KWD", 3, 1234),
    ("实付金额：USD 12.34", "USD", 2, 1234),
    ("支付金额：JPY 2850", "CNY", 2, None),
    ("支付金额：JPYSHOP2850", "JPY", 0, None),
])
def test_explicit_currency_retains_exact_minor_units_without_borrowing_other_codes(text, code, exponent, minor):
    result = parse_receipt_text(text, currency_code=code, minor_unit_exponent=exponent)
    assert result.amount_cents == minor
    if minor is not None:
        amount = next(item for item in result.candidates if item.field == "amount_cents" and item.value == minor)
        assert amount.role == "payment" and amount.currency_code == code


def test_printed_total_keeps_currency_and_does_not_take_cash_or_tax_table():
    raw = "Sub Total (RM)\n313.50\nTotal GST (RM):\n18.81\nTotal (RM):\n332.30\nCASH:\n400.00\nChange (RM):\n67.70\nGST SUMMARY\nTotal:\n313.50\n18.81"
    parsed = parse_receipt_text(raw, currency_code="MYR", minor_unit_exponent=2)
    assert parsed.amount_cents == 33230
    selected_id = next(item.selected_id for item in parsed.decisions if item.field == "amount_cents")
    selected = next(item for item in parsed.candidates if item.id == selected_id)
    assert "".join(raw[start:end] for start, end in selected.raw_spans) == "Total (RM):\n332.30"
    assert parse(raw).amount_cents is None  # RM cannot be stamped as installation CNY.
    assert parse_receipt_text("TOTAL:\nRM\n39.80\nCASH\nRM\n50.00\nCHANGE\nRM\n10.20",
        currency_code="MYR", minor_unit_exponent=2).amount_cents == 3980
    assert parse_receipt_text("CREDIT NOTE\nTOTAL:\nRM\n39.80",
        currency_code="MYR", minor_unit_exponent=2).amount_cents is None
    assert parse_receipt_text("TOTAL 15.00\nGRAND TOTAL 15.90\nCASH RM50.00",
        currency_code="MYR", minor_unit_exponent=2).amount_cents == 1590
    assert parse_receipt_text("EXAMPLE SDN BHD\nTOTAL (RM):\n15.90",
        currency_code="MYR", minor_unit_exponent=2).amount_cents == 1590
    assert parse_receipt_text("Total\n63.00\nInclusive GST @8.00%:\n63.80\nMaster Card\n63.00",
        currency_code="MYR", minor_unit_exponent=2).amount_cents == 6380
    assert parse("实付金额：USD 15.90").amount_cents is None
    assert parse_receipt_text("RM7.90\nRM0.47\nRM8.35\nGrand Total\n模糊\nCash RM10.50",
        currency_code="MYR", minor_unit_exponent=2).amount_cents is None


def test_printed_total_uses_its_own_row_when_ocr_orders_cash_after_label():
    blocks = [
        {"text": "RM34.80", "box": [[565, 1028], [720, 1026], [720, 1062], [566, 1064]]},
        {"text": "Total Incl. GST@6%", "box": [[50, 1041], [353, 1034], [354, 1069], [51, 1076]]},
        {"text": "RM100.00", "box": [[566, 1063], [718, 1060], [719, 1093], [567, 1096]]},
        {"text": "CASH", "box": [[50, 1077], [132, 1077], [132, 1106], [50, 1106]]},
    ]
    raw = "\n".join(block["text"] for block in blocks)
    parsed = parse_receipt_text(raw, currency_code="MYR", minor_unit_exponent=2, evidence_blocks=blocks)
    assert parsed.amount_cents == 3480
    selected_id = next(item.selected_id for item in parsed.decisions if item.field == "amount_cents")
    selected = next(item for item in parsed.candidates if item.id == selected_id)
    assert selected.block_indices == (0, 1)
    assert "".join(raw[start:end] for start, end in selected.raw_spans) == "RM34.80\nTotal Incl. GST@6%"
    assert parse_receipt_text(raw, currency_code="MYR", minor_unit_exponent=2).amount_cents is None


def test_printed_total_keeps_rounded_final_amount_and_does_not_read_item_count_as_money():
    for raw, expected in [
        ("Net Total: 19.01\nRounding -0.01\nNet Total Rounded: 19.00", 1900),
        ("Total Sales Incl GST 42.48\nRounding Adj 0.02\nTotal After Adj Incl GST 42.50\nCASH 50.00", 4250),
        ("Total Sales Inclusive 6% GST (3)\n39.90", None),
        ("TOTAL QUANTITY\n26\nTOTAL\n63.35?", None),
        ("TOTAL INCLUDES 6% GST\n3.98", None),
        ("Total 181.98\nRounding Adjustment 0.02\nRounding RM\n182.00", None),
        ("Total 37.89\nTotal 6% supplies (Inc. GST):\n10.68\nTotal Payable:\n48.57", 4857),
    ]:
        # A text-only block may span multiple lines and supplies no geometry.
        assert parse_receipt_text(raw, currency_code="MYR", minor_unit_exponent=2,
            evidence_blocks=[{"text": raw}]).amount_cents == expected
