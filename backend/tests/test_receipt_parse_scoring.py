from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.receipt_parse_common import _ReceiptContext, _ReceiptSignals
from app.services.receipt_parse_service import _context_quality_bonus, parse_receipt_text
from app.services.time_service import ensure_utc


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


def test_receipt_time_parser_accepts_client_timezone() -> None:
    raw_text = "交易时间：2026-04-30 23:30:00"

    shanghai = parse_receipt_text(raw_text, timezone_name="Asia/Shanghai")
    los_angeles = parse_receipt_text(raw_text, timezone_name="America/Los_Angeles")

    assert shanghai.expense_time is not None
    assert los_angeles.expense_time is not None
    assert _utc_iso(shanghai.expense_time) == "2026-04-30T15:30:00Z"
    assert _utc_iso(los_angeles.expense_time) == "2026-05-01T06:30:00Z"


def test_context_quality_bonus_rewards_structured_profile_evidence() -> None:
    context = _ReceiptContext(
        text="structured receipt",
        lines=("title", "amount", "merchant", "time", "success"),
        profile="alipay_bill_detail",
        signals=_ReceiptSignals(
            line_count=5,
            transaction_success_count=1,
            amount_label_count=1,
            merchant_label_count=1,
            time_label_count=1,
            discount_marker_count=1,
        ),
    )

    bonus = _context_quality_bonus(
        context=context,
        amount_candidate=None,
        merchant_candidate=None,
        time_candidate=None,
    )

    assert bonus > 0.06


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

    parsed = parse_receipt_text(raw_text)

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


def test_profile_calibration_keeps_mobility_provider_over_destination_text() -> None:
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

    parsed = parse_receipt_text(raw_text)

    assert parsed.amount_cents == 1173
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

    parsed = parse_receipt_text(raw_text)
    current_year = datetime.now(ZoneInfo("Asia/Shanghai")).year
    expected_time = ensure_utc(datetime(current_year, 5, 7, 15, 29, tzinfo=ZoneInfo("Asia/Shanghai")))

    assert parsed.amount_cents == 175479
    assert parsed.expense_time == expected_time
    assert parsed.confidence is not None and parsed.confidence >= 0.6


def test_taobao_flash_payment_sheet_prefers_bottom_amount_and_merchant() -> None:
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

    parsed = parse_receipt_text(raw_text)

    assert parsed.amount_cents == 2568
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

    parsed = parse_receipt_text(raw_text)

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

    parsed = parse_receipt_text(raw_text)

    assert parsed.amount_cents == 1900
    assert parsed.merchant == "巴南区卢记牛肉面"
    assert parsed.category == "餐饮"
