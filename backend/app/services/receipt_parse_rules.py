from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryHintRule:
    category: str
    keywords: tuple[str, ...]


AMOUNT_LABELS = (
    "交易金额",
    "支付金额",
    "实付金额",
    "订单金额",
    "消费金额",
    "付款金额",
    "支出金额",
    "金额",
    "实付",
    "合计",
    "总计",
)
MERCHANT_LABELS = (
    "收款方全称",
    "交易对象",
    "收款方",
    "付款给",
    "对方户名",
    "商家",
    "店铺",
    "门店",
    "平台",
    "应用",
    "来源",
)


@dataclass(frozen=True)
class LabeledAmountMatch:
    line_index: int
    label: str
    amount: str


@dataclass(frozen=True)
class LabeledMerchantMatch:
    line_index: int
    label: str
    value: str


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
RELATIVE_TIME_PATTERNS = [
    re.compile(r"(?<![年/\-.0-9])(\d{1,2})月(\d{1,2})日\s*(\d{1,2})[时:：](\d{2})(?:分(?:(\d{2})秒?)?)?"),
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


def parse_primary_amount_line(value: str) -> tuple[str | None, str] | None:
    """Parse a single OCR line that contains only a money amount."""
    tail = (value or "").strip()
    sign: str | None = None
    if tail.startswith(("﹣", "－", "−", "-")):
        sign = tail[0]
        tail = tail[1:].lstrip()
    tail = _strip_currency_prefix(tail)
    parsed = _read_amount_token(tail)
    if parsed is None:
        return None
    amount, tail = parsed
    tail = tail.lstrip()
    for suffix in ("人民币", "元"):
        if tail.startswith(suffix):
            tail = tail[len(suffix) :].lstrip()
            break
    if tail:
        return None
    return sign, amount


def is_primary_amount_line(value: str | None) -> bool:
    return parse_primary_amount_line(value or "") is not None


def iter_labeled_amount_matches(lines: tuple[str, ...] | list[str]) -> list[LabeledAmountMatch]:
    matches: list[LabeledAmountMatch] = []
    for line_index, line in enumerate(lines):
        for label, label_start in _label_hits(line, AMOUNT_LABELS):
            tail = line[label_start + len(label) :].lstrip()
            if tail.startswith((":", "：")):
                tail = tail[1:].lstrip()
            tail = _strip_currency_prefix(tail)
            parsed = _read_amount_token(tail)
            if parsed is None and not tail:
                parsed = _next_line_amount(lines, line_index)
            if parsed is None:
                continue
            amount, _tail = parsed
            matches.append(LabeledAmountMatch(line_index=line_index, label=label, amount=amount))
    return matches


def iter_labeled_merchant_matches(lines: tuple[str, ...] | list[str]) -> list[LabeledMerchantMatch]:
    matches: list[LabeledMerchantMatch] = []
    for line_index, line in enumerate(lines):
        stripped = line.strip()
        for label in sorted(MERCHANT_LABELS, key=len, reverse=True):
            if not stripped.startswith(label):
                continue
            value = stripped[len(label) :].lstrip()
            if value.startswith((":", "：")):
                value = value[1:].lstrip()
            value = _merchant_label_value(value)
            if 2 <= len(value) <= 60:
                matches.append(
                    LabeledMerchantMatch(line_index=line_index, label=label, value=value)
                )
            break
    return matches


def _label_hits(line: str, labels: tuple[str, ...]) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for label in sorted(labels, key=len, reverse=True):
        start = 0
        while True:
            index = line.find(label, start)
            if index < 0:
                break
            end = index + len(label)
            if not any(index < prev_index + len(prev_label) and end > prev_index for prev_label, prev_index in hits):
                hits.append((label, index))
            start = end
    return sorted(hits, key=lambda item: item[1])


def _strip_currency_prefix(value: str) -> str:
    tail = value.lstrip()
    for prefix in ("人民币", "RMB", "CNY", "¥", "￥"):
        if tail.upper().startswith(prefix):
            return tail[len(prefix) :].lstrip()
    return tail


def _read_amount_token(value: str) -> tuple[str, str] | None:
    text = value.lstrip()
    if not text or not text[0].isdigit():
        return None
    index = 0
    saw_decimal = False
    decimal_digits = 0
    while index < len(text):
        char = text[index]
        if char.isdigit():
            if saw_decimal:
                decimal_digits += 1
                if decimal_digits > 2:
                    break
            index += 1
            continue
        if char == "," and not saw_decimal:
            index += 1
            continue
        if char == "." and not saw_decimal:
            saw_decimal = True
            index += 1
            continue
        break
    token = text[:index].rstrip(",")
    if not token or token.endswith(".") or (saw_decimal and decimal_digits == 0):
        return None
    compact = token.replace(",", "")
    parts = compact.split(".")
    if len(parts) > 2 or not parts[0].isdigit():
        return None
    if len(parts) == 2 and (not parts[1].isdigit() or len(parts[1]) > 2):
        return None
    return token, text[index:]


def _next_line_amount(lines: tuple[str, ...] | list[str], line_index: int) -> tuple[str, str] | None:
    if line_index + 1 >= len(lines):
        return None
    return _read_amount_token(_strip_currency_prefix(lines[line_index + 1].strip()))


def _merchant_label_value(value: str) -> str:
    end = len(value)
    for separator in ("，", ",", "。", "；", ";"):
        found = value.find(separator)
        if found >= 0:
            end = min(end, found)
    return value[:end].strip()
MERCHANT_REJECT_SUBSTRINGS = ("金额", "时间", "方式", "订单", "机构", "奖励", "支付")
MERCHANT_NOISE_SUBSTRINGS = ("活动", "红包", "优惠", "奖励", "立减", "抵扣")

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
    "活动/券",
    "店铺活动/券",
    "平台红包",
}

PAYMENT_SHEET_MERCHANT_MARKERS = (
    "淘宝闪购商户",
    "美团外卖商户",
    "饿了么商户",
)
PAYMENT_SHEET_ACTION_MARKERS = (
    "正在付款中",
    "正在支付中",
    "付款中",
    "支付中",
    "确认支付",
)
PAYMENT_SHEET_PAYMENT_METHOD_MARKERS = (
    "储蓄卡",
    "信用卡",
    "花呗",
    "银行卡",
    "微信支付",
    "支付宝",
)

CATEGORY_HINT_RULES = (
    CategoryHintRule("餐饮", ("美团", "饿了么", "淘宝闪购", "kfc", "肯德基", "麦当劳", "餐", "外卖", "好想来", "零食", "小吃", "奶茶", "罗森", "便利店", "牛肉", "牛腩", "打包费", "配送费")),
    CategoryHintRule("购物", ("京东", "淘宝", "天猫", "拼多多", "购物", "超市", "批发", "商超")),
    CategoryHintRule("交通", ("滴滴", "高德", "地铁", "公交", "打车")),
    CategoryHintRule("AI订阅", ("openai", "claude", "gemini", "kimi", "chatgpt")),
    CategoryHintRule("游戏", ("steam", "taptap", "playstation", "任天堂")),
    CategoryHintRule("医疗", ("医院", "药房", "买药")),
    CategoryHintRule("通讯", ("中国移动", "中国联通", "中国电信", "话费")),
)
