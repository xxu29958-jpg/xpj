from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CategoryHintRule:
    category: str
    keywords: tuple[str, ...]


PRIMARY_AMOUNT_LINE_PATTERN = re.compile(
    r"^(?P<sign>[-−﹣－])?\s*(?:人民币|RMB|CNY|¥|￥)?\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:元|人民币)?$",
    re.IGNORECASE,
)
LABELED_AMOUNT_PATTERN = re.compile(
    r"(?P<label>交易金额|支付金额|实付金额|订单金额|消费金额|付款金额|支出金额|金额|实付|合计|总计)"
    r"\s*[:：]?\s*(?:人民币|RMB|CNY|¥|￥)?\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
CURRENCY_AMOUNT_PATTERN = re.compile(r"(?:¥|￥)\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)")
YUAN_AMOUNT_PATTERN = re.compile(r"(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:元|人民币)")
CLOCK_LINE_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")
PAYMENT_METHOD_LINE_PATTERN = re.compile(r"^使用.+支付$")

TIME_PATTERNS = [
    re.compile(
        r"(?:交易时间|支付时间|付款时间|消费时间|下单时间|订单时间)"
        r"\s*[:：]?\s*(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})日?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?"
    ),
    re.compile(
        r"(?:创建时间|来电时间|时间)"
        r"\s*[:：]?\s*(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})日?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?"
    ),
    re.compile(r"(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})日?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?"),
]

MERCHANT_LABEL_PATTERN = re.compile(
    r"(?:^|\n)(?P<label>商家|收款方全称|收款方|付款给|对方户名|交易对象|店铺|门店|平台|应用|来源)"
    r"\s*[:：]?\s*(?P<value>[^\n\r，,。；;]{2,60})"
)

TRANSACTION_SUCCESS_KEYWORDS = ("交易成功", "支付成功", "付款成功")
DISCOUNT_AMOUNT_LABELS = ("优惠", "立减", "红包", "券", "奖励", "抵扣")
MONEY_MARKERS = ("¥", "￥", "元", "人民币")
UPPER_MONEY_MARKERS = ("RMB", "CNY")

AMOUNT_LABEL_SCORES = {
    "交易金额": 78,
    "支付金额": 76,
    "实付金额": 82,
    "付款金额": 76,
    "支出金额": 76,
    "消费金额": 72,
    "实付": 76,
    "合计": 45,
    "总计": 45,
    "订单金额": 40,
    "金额": 35,
}
INLINE_AMOUNT_PATTERNS = (
    (CURRENCY_AMOUNT_PATTERN, "currency", 28),
    (YUAN_AMOUNT_PATTERN, "yuan", 22),
)

MERCHANT_LABEL_SCORES = {
    "商家": 88,
    "店铺": 84,
    "门店": 84,
    "交易对象": 82,
    "付款给": 82,
    "收款方": 72,
    "收款方全称": 58,
    "平台": 45,
    "应用": 45,
    "来源": 42,
}
MERCHANT_REJECT_SUBSTRINGS = ("金额", "时间", "方式", "订单", "机构", "奖励", "支付")

SUCCESS_PAGE_SKIP_LINES = {
    "获得森林能量",
    "交易方式",
    "付款方式",
    "花呗",
    "去查看",
    "立即领取",
    "待领取",
    "完成",
    "回首页",
}
SUCCESS_PAGE_AD_KEYWORDS = ("评价", "红包", "扫街榜", "限时", "打车", "高德", "领取", "优惠", "奖励")

MERCHANT_KEYWORDS = (
    "中国建设银行",
    "招商银行",
    "工商银行",
    "农业银行",
    "中国银行",
    "交通银行",
    "邮储银行",
    "支付宝",
    "微信支付",
    "美团",
    "饿了么",
    "京东",
    "京东快递",
    "淘宝",
    "天猫",
    "拼多多",
    "滴滴",
    "高德",
    "OpenAI",
    "Claude",
    "Gemini",
    "Kimi",
    "Steam",
    "TapTap",
)
BANK_KEYWORDS = (
    "中国建设银行",
    "招商银行",
    "工商银行",
    "农业银行",
    "中国银行",
    "交通银行",
    "邮储银行",
)
MERCHANT_IGNORED_LINES = {
    "账单详情",
    "账单详情>",
    "全部账单",
    "交易成功",
    "支付成功",
    "付款成功",
    "交易状态",
    "查看账单详情",
    "商家名片",
    "我的账单",
    "支付服务",
    "摇优惠",
    "回首页",
    "订单金额",
    "支付时间",
    "付款方式",
    "商品说明",
    "支付奖励",
    "收单机构",
    "清算机构",
    "收款方全称",
    "订单号",
    "商家订单号",
}

CATEGORY_HINT_RULES = (
    CategoryHintRule("餐饮", ("美团", "饿了么", "kfc", "肯德基", "麦当劳", "餐", "外卖", "好想来", "零食", "小吃", "奶茶", "罗森", "便利店")),
    CategoryHintRule("购物", ("京东", "淘宝", "天猫", "拼多多", "购物", "超市", "批发", "商超")),
    CategoryHintRule("交通", ("滴滴", "高德", "地铁", "公交", "打车")),
    CategoryHintRule("AI订阅", ("openai", "claude", "gemini", "kimi", "chatgpt")),
    CategoryHintRule("游戏", ("steam", "taptap", "playstation", "任天堂")),
    CategoryHintRule("医疗", ("医院", "药房", "买药")),
    CategoryHintRule("通讯", ("中国移动", "中国联通", "中国电信", "话费")),
)
