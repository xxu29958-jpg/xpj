"""A displayed payment's amount and counterparty retain their status evidence."""
import pytest

from app.services.receipt_parse_service import parse_receipt_text


def parse(lines):
    blocks = [{"text": line, "box": [[0, i * 40], [300, i * 40],
        [300, i * 40 + 30], [0, i * 40 + 30]], "confidence": .99} for i, line in enumerate(lines)]
    return parse_receipt_text("\n".join(lines), evidence_blocks=blocks, currency_code="CNY",
        minor_unit_exponent=2, timezone_name="Asia/Shanghai")


@pytest.mark.parametrize("lines,amount_index,status_index,merchant_index", [
    (["支付成功", "￥8.50", "青禾零食店"], 1, 0, 2),
    (["青禾超市", "-18.40", "支付成功", "支付时间", "2026-10-20 12:30"], 1, 2, 0),
    (["青禾出行", "-12.09", "自动扣款成功"], 1, 2, 0),
])
def test_success_context_gives_the_selected_fields_roles_and_traceable_status(
        lines, amount_index, status_index, merchant_index):
    result = parse(lines)
    selected = {decision.field: decision.selected_id for decision in result.decisions}
    amount = next(c for c in result.candidates if c.id == selected['amount_cents'])
    merchant = next(c for c in result.candidates if c.id == selected['merchant'])
    assert amount.role == 'payment'
    assert set(amount.block_indices) == {amount_index, status_index}
    assert merchant.role == 'merchant'
    assert set(merchant.block_indices) == {merchant_index, status_index}


def test_shop_bound_in_description_stays_above_the_payment_platform_title():
    result = parse(["购物平台", "-18.40", "支付成功", "商品说明", "青禾茶店(城南店)外卖订单"])
    assert result.merchant == '青禾茶店(城南店)'
    assert result.amount_cents == 1840


def test_success_does_not_turn_adjacent_balance_or_discount_into_payment():
    result = parse(["支付成功", "余额", "￥900.00", "优惠", "￥8.00"])
    assert result.amount_cents is None
    assert {c.role for c in result.candidates if c.field == 'amount_cents'} == {'balance', 'discount'}


@pytest.mark.parametrize("label", ["券", "订单说明"])
def test_standalone_price_does_not_override_a_competing_inline_amount(label):
    result = parse(["支付成功", "青禾茶店", "金额：18.00元", label, "￥50.00"])
    assert result.amount_cents == 1800
    assert not any(c.value == 5000 and c.role == "payment" for c in result.candidates)


def test_repeated_cards_keep_each_status_and_selected_payment_in_its_event():
    result = parse(["服务消息", "青禾超市", "08:20", "付款成功", "￥150.00", "查看详情",
        "青禾超市", "08:21", "付款成功", "￥160.00", "查看详情"])
    assert result.amount_cents is None
    assert len(result.events) == 2
    for event, amount_value in zip(result.events, [15000, 16000], strict=True):
        selected = [c for c in result.candidates if c.event_id == event['id'] and c.event_selected]
        amount = next(c for c in selected if c.field == 'amount_cents')
        merchant = next(c for c in selected if c.field == 'merchant')
        assert amount.value == amount_value and amount.role == 'payment'
        assert merchant.value == '青禾超市' and merchant.role == 'merchant'
        assert set(amount.block_indices) <= set(event['block_indices'])
        assert set(merchant.block_indices) <= set(event['block_indices'])


@pytest.mark.parametrize("lines,value,indices", [
    (["支付成功 ￥39.50", "付款方式", "某银行储蓄卡", "支付奖励"], 3950, {0}),
    (["支付成功", "出行服务", "开发票", "联系客服", "14.80元", "全程2.57公里"], 1480, {0, 4}),
])
def test_one_completed_payment_keeps_its_amount_role_across_card_layouts(lines, value, indices):
    result = parse(lines)
    selected_id = next(d.selected_id for d in result.decisions if d.field == 'amount_cents')
    chosen = next(c for c in result.candidates if c.id == selected_id)
    assert chosen.value == value and chosen.role == 'payment'
    assert set(chosen.block_indices) == indices


@pytest.mark.parametrize("line,role", [("支付金额18.00", "payment"), ("退款金额18.00", "refund")])
def test_field_evidence_displays_the_original_label_and_amount_once(line, role):
    text = "  青禾便利店\r\n  " + line + "\r\n"
    result = parse_receipt_text(text, currency_code="CNY", minor_unit_exponent=2)
    chosen = next(c for c in result.candidates if c.field == "amount_cents" and c.role == role)
    assert "".join(text[start:end] for start, end in chosen.raw_spans) == line
