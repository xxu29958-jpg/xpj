from __future__ import annotations

from app.services.receipt_parse_service import parse_receipt_text


def _utc_iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


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

    parsed = parse_receipt_text(raw_text)

    assert parsed.amount_cents == 1789
    assert parsed.merchant == "好想来零食乐园"
    assert parsed.category == "餐饮"
    assert parsed.expense_time is not None
    assert _utc_iso(parsed.expense_time) == "2026-05-05T13:38:13Z"
    assert parsed.confidence is not None and parsed.confidence >= 0.8


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

    parsed = parse_receipt_text(raw_text)

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

    parsed = parse_receipt_text(raw_text)

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

    parsed = parse_receipt_text(raw_text)

    assert parsed.amount_cents == 1851
    assert parsed.merchant == "中国建设银行"
    assert parsed.expense_time is not None
    assert _utc_iso(parsed.expense_time) == "2026-05-04T08:23:25Z"
