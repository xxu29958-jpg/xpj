from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.receipt_parse_service import parse_receipt_text


def _utc_iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_cny(raw_text: str, *, timezone_name: str | None = None, reference_time=None):
    return parse_receipt_text(
        raw_text,
        timezone_name=timezone_name,
        currency_code="CNY",
        minor_unit_exponent=2,
        reference_time=reference_time,
    )


def test_material_amount_remains_available_beside_a_discount_and_advertisements():
    parsed = _parse_cny("\n".join([
        "支付成功", "城市出行-经济型", "再来一单", "开发票", "联系客服", "费用明细",
        "12.6元", "优惠0.4元", "全程2公里", "活动专区", "10元", "无门槛打车券",
    ]))
    assert parsed.amount_cents == 1260
    assert any(candidate.value == 1260 for candidate in parsed.candidates if candidate.field == "amount_cents")


def test_material_total_keeps_its_role_next_to_a_discount_not_the_nearby_item_price():
    parsed = _parse_cny("支付成功\n商品原价\n¥36\n包装费\n¥1\n合计\n已优惠¥8.5 ¥28.5")
    assert parsed.amount_cents == 2850
    selected = next(candidate for candidate in parsed.candidates
        if candidate.id == next(decision.selected_id for decision in parsed.decisions if decision.field == "amount_cents"))
    assert selected.role == "total"
    assert "合计" in "".join("支付成功\n商品原价\n¥36\n包装费\n¥1\n合计\n已优惠¥8.5 ¥28.5"[start:end]
        for start, end in selected.raw_spans)


@pytest.mark.parametrize("order", [(0, 1, 2, 3), (2, 0, 3, 1)])
def test_material_merchant_label_binds_value_on_its_row_with_original_provenance(order):
    blocks = [
        {"text": "商家名称", "box": [[0, 200], [80, 200], [80, 220], [0, 220]]},
        {"text": "BlueBay", "box": [[180, 200], [320, 200], [320, 220], [180, 220]]},
        {"text": "商品说明", "box": [[0, 300], [80, 300], [80, 320], [0, 320]]},
        {"text": "会员续费", "box": [[180, 300], [320, 300], [320, 320], [180, 320]]},
    ]
    blocks = [blocks[index] for index in order]
    text = "\n".join(block["text"] for block in blocks)
    parsed = parse_receipt_text(text, currency_code="CNY", minor_unit_exponent=2, evidence_blocks=blocks)
    assert parsed.merchant == "BlueBay"
    selected = next(candidate for candidate in parsed.candidates
        if candidate.id == next(decision.selected_id for decision in parsed.decisions if decision.field == "merchant"))
    assert {blocks[index]["text"] for index in selected.block_indices} == {"商家名称", "BlueBay"}


def test_material_merchant_is_the_scoped_store_not_the_payment_platform():
    text = "账单详情\n淘宝闪购\n-28.50\n支付成功\n商品说明\n晨光茶饮(中央路店)外卖订单\n付款方式\n信用卡"
    parsed = _parse_cny(text)
    assert parsed.merchant == "晨光茶饮(中央路店)"
    assert any(candidate.value == "淘宝闪购" for candidate in parsed.candidates if candidate.field == "merchant")


def test_material_equal_amount_cards_do_not_form_one_cross_event_draft():
    text = "支付成功\n支付金额：20.00元\n商家：晨光商店\n支付时间：2026-02-03 10:20:00\n" + \
        "支付成功\n支付金额：20.00元\n商家：晴天商店\n支付时间：2026-02-04 10:20:00"
    parsed = _parse_cny(text, timezone_name="Asia/Shanghai")
    assert parsed.amount_cents is None and parsed.merchant is None and parsed.expense_time is None
    assert all(decision.reason == "multiple_transaction_events" for decision in parsed.decisions)
    assert len(parsed.events) == 2
    for event in parsed.events:
        candidates = [candidate for candidate in parsed.candidates if candidate.event_id == event["id"]]
        assert len({candidate.value for candidate in candidates if candidate.field == "merchant"}) == 1


@pytest.mark.parametrize("heading,amounts,prefix", [
    ("交易成功", ("¥17.89", "¥29.20"), True),
    ("交易成功", ("-17.89", "-17.89"), True),
    ("交易成功", ("支付金额：17.89元", "支付金额：29.20元"), True),
    ("交易成功", ("支付金额\n17.89", "支付金额\n29.20"), True),
    ("支付成功", ("-17.89", "-29.20"), False),
    ("扣款成功", ("支付金额17.89", "支付金额29.20"), False),
])
def test_material_card_evidence_keeps_prefix_fields_with_its_own_success(heading, amounts, prefix):
    cards = ["\n".join([merchant, amount, heading, f"支付时间2026-10-{18 + index} 12:00", "查看详情"]
        if prefix else [heading, "商家：" + merchant, amount, f"支付时间2026-10-{18 + index} 12:00", "查看详情"])
        for index, (merchant, amount) in enumerate(zip(("松针小笼包", "罗森便利店"), amounts, strict=True))]
    raw = "\n".join(cards)
    parsed = _parse_cny(raw)
    assert len(parsed.events) == 2
    assert parsed.amount_cents is None and parsed.merchant is None
    for event, card, merchant in zip(parsed.events, cards, ("松针小笼包", "罗森便利店"), strict=True):
        evidence = "".join(raw[start:end] for start, end in event["raw_spans"])
        assert evidence.strip() == card
        candidates = [item for item in parsed.candidates if item.event_id == event["id"]]
        assert {item.value for item in candidates if item.field == "merchant"} == {merchant}
        assert any(item.field == "amount_cents" for item in candidates)


def test_material_ui_prefix_is_not_a_merchant_label_but_delimited_store_still_is():
    raw = "罗森便利店\n-17.89\n交易成功\n商家服务：联系客服\n支付时间2026-10-18 12:00"
    parsed = _parse_cny(raw)
    assert parsed.merchant == "罗森便利店"
    assert not any(item.field == "merchant" and item.value == "服务：联系客服" for item in parsed.candidates)
    assert _parse_cny("支付成功\n商家：罗森便利店\n支付金额17.89").merchant == "罗森便利店"


def test_material_card_limit_leaves_the_unparsed_tail_outside_the_last_event():
    cards = [f"门店{index}号\n-17.89\n交易成功\n查看详情" for index in range(21)]
    text = "\n".join(cards)
    parsed = _parse_cny(text)
    assert len(parsed.events) == 20
    assert parsed.events[-1]["raw_spans"][-1][1] <= text.index(cards[-1])
    assert not any(candidate.field == "merchant" and candidate.value == "门店20号" for candidate in parsed.candidates)


@pytest.mark.parametrize("merchant_label", ["商家：", "商家名称\n"])
def test_material_split_fields_and_their_labels_stay_in_the_same_event(merchant_label):
    cards = [f"{merchant_label}{merchant}\n支付金额\n{amount}\n交易成功\n查看详情"
        for merchant, amount in [("松针小笼包", "17.89"), ("罗森便利店", "29.20")]]
    raw = "\n".join(cards)
    parsed = _parse_cny(raw)
    assert len(parsed.events) == 2 and parsed.merchant is None and parsed.amount_cents is None
    for event, card, merchant in zip(parsed.events, cards, ["松针小笼包", "罗森便利店"], strict=True):
        assert "".join(raw[start:end] for start, end in event["raw_spans"]).strip() == card
        assert {item.value for item in parsed.candidates if item.event_id == event["id"]
            and item.field == "merchant"} == {merchant}


@pytest.mark.parametrize("second_amount", ["17.89", "29.20"])
def test_material_inline_bank_amounts_are_separate_transaction_evidence(second_amount):
    cards = [f"交易提醒\n尾号1234支出人民币{amount}元\n商户：{merchant}"
        for amount, merchant in [("17.89", "松针小笼包"), (second_amount, "罗森便利店")]]
    raw = "\n".join(cards)
    parsed = _parse_cny(raw)
    assert len(parsed.events) == 2 and parsed.amount_cents is None and parsed.merchant is None
    assert all(item.reason == "multiple_transaction_events" for item in parsed.decisions)
    for event, card in zip(parsed.events, cards, strict=True):
        assert "".join(raw[start:end] for start, end in event["raw_spans"]).strip() == card
        assert any(item.field == "amount_cents" and item.event_id == event["id"] for item in parsed.candidates)


@pytest.mark.parametrize("merchant", ["城市打车", "7:11便利店", "8:30咖啡", "7:11 24小时便利店"])
def test_material_status_clock_is_not_a_merchant_and_auto_debit_is_a_paid_event(merchant):
    parsed = _parse_cny(f"17:04 8…\n账单详情\n{merchant}\n-13.20\n自动扣款成功\n付款方式\n信用卡")
    assert parsed.amount_cents == 1320
    assert parsed.merchant == merchant
    assert not any(candidate.field == "merchant" and str(candidate.value).startswith("17:04")
        for candidate in parsed.candidates)


def test_scoring_prefers_alipay_primary_amount_merchant_and_time() -> None:
    raw_text = "\n".join(
        [
            "账单详情",
            "好想来零食乐园",
            "-17.89",
            "交易成功",
            "订单金额",
            "18.00",
            "碰一下立减",
            "-0.11",
            "支付时间",
            "2026-05-05 21:38:13",
            "付款方式",
            "花呗",
            "商品说明",
            "重庆巴南区珠江城店",
            "收单机构",
            "招商银行股份有限公司",
            "清算机构",
            "中国银联股份有限公司",
            "收款方全称",
            "巴南区财进宁食品经营部（个体工商户）",
        ]
    )

    parsed = _parse_cny(raw_text)

    assert parsed.amount_cents == 1789
    assert parsed.merchant == "好想来零食乐园"
    assert parsed.category == "餐饮"
    assert parsed.expense_time is not None
    assert _utc_iso(parsed.expense_time) == "2026-05-05T13:38:13Z"
    assert parsed.confidence is not None and parsed.confidence >= 0.8


def test_receipt_time_parser_accepts_client_timezone() -> None:
    raw_text = "交易时间：2026-04-30 23:30:00"

    shanghai = _parse_cny(raw_text, timezone_name="Asia/Shanghai")
    los_angeles = _parse_cny(raw_text, timezone_name="America/Los_Angeles")

    assert shanghai.expense_time is not None
    assert los_angeles.expense_time is not None
    assert _utc_iso(shanghai.expense_time) == "2026-04-30T15:30:00Z"
    assert _utc_iso(los_angeles.expense_time) == "2026-05-01T06:30:00Z"


def test_profile_calibration_demotes_alipay_order_amount() -> None:
    raw_text = "\n".join(
        [
            "账单详情",
            "好想来零食乐园",
            "-17.89",
            "交易成功",
            "订单金额 18.00",
            "碰一下立减 -0.11",
            "支付时间 2026-05-05 21:38:13",
            "收款方全称 巴南区财进宁食品经营部",
        ]
    )

    parsed = _parse_cny(raw_text)

    assert parsed.amount_cents == 1789
    assert parsed.merchant == "好想来零食乐园"
    assert parsed.category == "餐饮"


def test_scoring_does_not_let_ad_keywords_steal_category() -> None:
    raw_text = "\n".join(
        [
            "支付成功",
            "￥7.50",
            "获得森林能量",
            "20g",
            "罗森便利店",
            "￥ 7.50",
            "交易方式",
            "花呗",
            "高德",
            "写真实评价，领10元打车红包",
            "券后￥0.01",
        ]
    )

    parsed = _parse_cny(raw_text)

    assert parsed.amount_cents == 750
    assert parsed.merchant == "罗森便利店"
    assert parsed.category == "餐饮"


def test_scoring_uses_repeated_amount_as_cross_evidence() -> None:
    raw_text = "\n".join(
        [
            "支付成功",
            "￥21.82",
            "获得森林能量",
            "20g",
            "乐尔乐特价批发超市",
            "￥21.82",
            "订单金额",
            "22.00",
            "碰一下立减",
            "-￥0.18",
            "本店特价限时抢购",
        ]
    )

    parsed = _parse_cny(raw_text)

    assert parsed.amount_cents == 2182
    assert parsed.merchant == "乐尔乐特价批发超市"
    assert parsed.category == "购物"


def test_scoring_prefers_business_time_over_generic_time() -> None:
    raw_text = "\n".join(
        [
            "商品详情：超级咸蛋黄狮子头+泡椒脆笋鸭丝单人套餐",
            "中国建设银行",
            "交易提醒",
            "创建时间：2026-05-04 06:49:50",
            "交易时间：2026年5月4日 16:23:25",
            "交易金额：18.51（人民币）",
        ]
    )

    parsed = _parse_cny(raw_text)

    assert parsed.amount_cents == 1851
    assert parsed.merchant == "中国建设银行"
    assert parsed.expense_time is not None
    assert _utc_iso(parsed.expense_time) == "2026-05-04T08:23:25Z"


@pytest.mark.parametrize("order", [(0, 1, 2, 3), (2, 1, 3, 0)])
@pytest.mark.parametrize("other_label, label_y, role", [
    ("下单时间", 70, "order"), ("打印时间Print time", 56, "printed"),
    ("支付时间/打印时间", 70, "unknown"),
])
def test_time_roles_follow_page_rows_instead_of_ocr_serialization(order, other_label, label_y, role) -> None:
    rows = [("支付时间", 10, 20), (other_label, 10, label_y),
        ("2026-05-04 16:23", 200, 20), ("2026-05-04 16:00", 200, 70)]
    blocks = [{"text": rows[index][0], "box": [[rows[index][1], rows[index][2]],
        [rows[index][1] + 150, rows[index][2]], [rows[index][1] + 150, rows[index][2] + 20],
        [rows[index][1], rows[index][2] + 20]]} for index in order]
    raw = "\n".join(block["text"] for block in blocks)
    parsed = parse_receipt_text(raw, timezone_name="Asia/Shanghai", evidence_blocks=blocks,
        currency_code="CNY", minor_unit_exponent=2)
    assert _utc_iso(parsed.expense_time) == "2026-05-04T08:23:00Z"
    payment = next(item for item in parsed.candidates if item.role == "payment")
    assert set(payment.block_indices) == {order.index(0), order.index(2)}
    assert {raw[start:end] for start, end in payment.raw_spans} == {"支付时间", "2026-05-04 16:23"}
    other = next(item for item in parsed.candidates if item.local_value == "2026-05-04T16:00")
    assert other.role == role
    if role != "unknown":
        assert other.review_reason == "non_transaction_time"
        assert set(other.block_indices) == {order.index(1), order.index(3)}


def test_labeled_amount_and_merchant_parse_with_long_spacing() -> None:
    raw_text = "\n".join(
        [
            "商家：罗森便利店",
            "金额：" + (" " * 120) + "12.34",
            "交易成功",
        ]
    )

    parsed = _parse_cny(raw_text)

    assert parsed.amount_cents == 1234
    assert parsed.merchant == "罗森便利店"


@pytest.mark.parametrize("label,role", [("打印时间", "printed"), ("下单时间", "order"), ("支付时间", "payment")])
@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_vertical_time_labels_do_not_turn_non_transaction_times_into_expenses(label, role, order):
    rows = [{"text": label, "box": [[10, 10], [160, 10], [160, 30], [10, 30]]},
        {"text": "2026-01-01 09:00", "box": [[10, 36], [190, 36], [190, 56], [10, 56]]}]
    blocks = [rows[index] for index in order]
    raw = "\n".join(block["text"] for block in blocks)
    parsed = parse_receipt_text(raw, evidence_blocks=blocks, currency_code="CNY", minor_unit_exponent=2)
    value = next(item for item in parsed.candidates if item.field == "expense_time")
    assert value.role == role
    assert {raw[start:end] for start, end in value.raw_spans} == {label, "2026-01-01 09:00"}
    assert (parsed.expense_time is not None) == (role == "payment")


def test_future_mobility_payment_keeps_merchant_and_amount_evidence_without_filling_expense() -> None:
    raw_text = "\n".join(
        [
            "花溪工业园区",
            "高德地图",
            "21:15",
            "好想来零食乐园（重庆巴南区珠江城店）",
            "订单支付",
            "鲸志出行-经济型|余师傅·渝AA77599",
            "11.73元",
            "费用说明）",
            "起步价",
            "11.73元",
            "高德打车",
            "已开启免密支付，将于05月06日21:17自动扣款",
            "确认支付",
        ]
    )

    parsed = _parse_cny(raw_text)

    assert parsed.amount_cents is None
    assert any(item.field == "amount_cents" and item.value == 1173 for item in parsed.candidates)
    assert next(item for item in parsed.decisions if item.field == "amount_cents").reason == "transaction_not_completed"
    assert parsed.merchant == "高德"
    assert parsed.category == "交通"


def test_bank_push_reminder_extracts_inline_spend_time() -> None:
    raw_text = "\n".join(
        [
            "15:30",
            "骑士",
            "已接单",
            "动账提醒",
            "现在",
            "您尾号0436的储蓄账户5月7日15时29分",
            "支出人民币1754.79元。点击查看>>",
            "可用额度(元)",
            "50,000.00",
            "开始借款",
        ]
    )

    reference = datetime(2025, 5, 8, tzinfo=UTC)
    parsed = _parse_cny(raw_text, reference_time=reference)

    assert parsed.amount_cents == 175479
    assert parsed.expense_time is None
    candidate = next(item for item in parsed.candidates if item.field == "expense_time")
    assert candidate.local_value == "2025-05-07T15:29"
    assert candidate.inferred_components == ("year",)
    assert candidate.reference_time == reference.isoformat()
    assert candidate.review_reason == "year_inferred_from_capture_reference"


def test_taobao_payment_in_progress_preserves_amount_evidence_without_claiming_spend() -> None:
    raw_text = "\n".join(
        [
            "15:17",
            "4G",
            "送至：华陶家园8幢二单元二杠二；17384071884",
            "【收藏福利】潮汕牛肉丸2颗",
            "￥2",
            "精品牛腩拒绝黑餐，以清淡口为主",
            "￥0",
            "打包费?",
            "配送费",
            "惊喜减3.3元￥3.4￥0.1",
            "店铺活动/券",
            "-￥2",
            "拭目以待",
            "平台红包",
            "淘宝闪购商户",
            "￥25.68",
            "厦门银行储蓄卡（7350）",
            "正在付款中...",
        ]
    )

    parsed = _parse_cny(raw_text)

    assert parsed.amount_cents is None
    assert any(item.field == "amount_cents" and item.value == 2568 for item in parsed.candidates)
    assert next(item for item in parsed.decisions if item.field == "amount_cents").reason == "transaction_not_completed"
    assert parsed.merchant == "淘宝闪购商户"
    assert parsed.category == "餐饮"


def test_alipay_bill_detail_prefers_specific_merchant_over_short_alias() -> None:
    raw_text = "\n".join(
        [
            "22:46",
            "l 4G 79",
            "账单详情",
            "闪购",
            "淘宝闪购",
            "-25.68",
            "交易成功",
            "支付时间",
            "2026-05-0715:17:09",
            "付款方式",
            "花呗>",
            "商品说明",
            "廣仔牛腩饭外卖订单",
            "支付奖励",
            "立即领取3积分",
            "账单分类",
            "餐饮美食>",
        ]
    )

    parsed = _parse_cny(raw_text)

    assert parsed.amount_cents == 2568
    assert parsed.merchant == "淘宝闪购"
    assert parsed.category == "餐饮"
    assert parsed.expense_time is not None
    assert _utc_iso(parsed.expense_time) == "2026-05-07T07:17:09Z"


def test_status_bar_battery_number_does_not_beat_payment_amount() -> None:
    raw_text = "\n".join(
        [
            "08:30",
            "5G",
            "72",
            "支付成功",
            "巴南区卢记牛肉面",
            "¥19.00",
            "摇一摇，有优惠",
            "返回商家",
        ]
    )

    parsed = _parse_cny(raw_text)

    assert parsed.amount_cents == 1900
    assert parsed.merchant == "巴南区卢记牛肉面"
    assert parsed.category == "餐饮"


@pytest.mark.parametrize(
    ("currency_code", "minor_unit_exponent", "raw_text", "expected_minor", "expected_items"),
    [
        (
            "CNY",
            2,
            "示例超市\n苹果 x1 10.00\n牛奶 x1 2.34\n合计：12.34",
            1234,
            (1000, 234),
        ),
        (
            "JPY",
            0,
            "示例超市\n苹果 x1 1000\n牛奶 x1 200\n合计：1200",
            1200,
            (1000, 200),
        ),
        (
            "KRW",
            0,
            "示例超市\n苹果 x1 1000\n牛奶 x1 200\n合计：1200",
            1200,
            (1000, 200),
        ),
    ],
)
def test_receipt_money_uses_explicit_frozen_currency_exponent(
    currency_code: str,
    minor_unit_exponent: int,
    raw_text: str,
    expected_minor: int,
    expected_items: tuple[int, int],
) -> None:
    parsed = parse_receipt_text(
        raw_text,
        currency_code=currency_code,
        minor_unit_exponent=minor_unit_exponent,
    )

    assert parsed.amount_cents == expected_minor
    assert tuple(item.amount_cents for item in parsed.items) == expected_items


@pytest.mark.parametrize(
    ("currency_code", "minor_unit_exponent", "raw_text"),
    [
        ("JPY", 0, "示例超市\n合计：1200.50"),
        ("JPY", 2, "示例超市\n合计：1200"),
        ("JPY", 0, "示例超市\n交易金额：1200（人民币）"),
        (None, None, "示例超市\n合计：12.34"),
    ],
)
def test_receipt_money_fails_closed_without_matching_explicit_context(
    currency_code: str | None,
    minor_unit_exponent: int | None,
    raw_text: str,
) -> None:
    parsed = parse_receipt_text(
        raw_text,
        currency_code=currency_code,
        minor_unit_exponent=minor_unit_exponent,
    )

    assert parsed.amount_cents is None
    assert parsed.items == ()
