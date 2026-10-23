from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.receipt_parse_money import _EXPLICIT_CURRENCY_MARKERS
from app.services.receipt_parse_structure import related_value_index

_CURRENCY_PREFIXES = sorted(
    {marker for markers in _EXPLICIT_CURRENCY_MARKERS.values() for marker in markers} | {"¥", "￥"},
    key=len, reverse=True,
)
CURRENCY_PREFIX_PATTERN = "(?:" + "|".join(re.escape(value) for value in _CURRENCY_PREFIXES) + ")"

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
    "商家名称",
    "商户名称",
    "收款方全称",
    "交易对象",
    "收款方",
    "付款给",
    "对方户名",
    "商家",
    "商户",
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
    normalized_span: tuple[int, int]


@dataclass(frozen=True)
class LabeledMerchantMatch:
    line_index: int
    label: str
    value: str
    value_span: tuple[int, int]
    label_span: tuple[int, int]


PRIMARY_AMOUNT_LINE_PATTERN = re.compile(
    r"^(?P<sign>[-−﹣－])?\s*(?:人民币|RMB|CNY|¥|￥)?\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:元|人民币)?$",
    re.IGNORECASE,
)
LABELED_AMOUNT_PATTERN = re.compile(
    r"(?P<label>交易金额|支付金额|实付金额|订单金额|消费金额|付款金额|支出金额|金额|实付|合计|总计)"
    r"\s*[:：]?\s*(?:人民币|RMB|CNY|¥|￥)?\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
CURRENCY_AMOUNT_PATTERN = re.compile(r"(?:¥|￥)\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]+)?)(?![0-9.,])")
YUAN_AMOUNT_PATTERN = re.compile(r"(?<![0-9.,])(?P<amount>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:元|人民币)")
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

TRANSACTION_SUCCESS_KEYWORDS = ("交易成功", "支付成功", "付款成功", "自动扣款成功", "扣款成功")
DISCOUNT_AMOUNT_LABELS = ("优惠", "立减", "红包", "券", "奖励", "抵扣")
MONEY_MARKERS = ("¥", "￥", "元", "人民币")
UPPER_MONEY_MARKERS = ("RMB", "CNY", "RM")

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
    "商家名称": 96,
    "商户名称": 96,
    "商家": 88,
    "商户": 88,
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


def iter_labeled_amount_matches(lines: tuple[str, ...] | list[str],
        blocks: Sequence[dict] | None = None) -> list[LabeledAmountMatch]:
    matches: list[LabeledAmountMatch] = []
    offset = 0
    for line_index, line in enumerate(lines):
        for label, label_start in _label_hits(line, AMOUNT_LABELS):
            tail = line[label_start + len(label) :].lstrip()
            if tail.startswith((":", "：")):
                tail = tail[1:].lstrip()
            tail = _strip_currency_prefix(tail)
            amount_start = offset + len(line) - len(tail)
            parsed = _read_amount_token(tail)
            if parsed is None and not tail:
                parsed = _next_line_amount(lines, line_index)
                if parsed is not None:
                    next_tail = _strip_currency_prefix(lines[line_index + 1].strip())
                    amount_start = offset + len(line) + 1 + len(lines[line_index + 1]) - len(next_tail)
            if parsed is None:
                continue
            amount, _tail = parsed
            matches.append(LabeledAmountMatch(line_index=line_index, label=label, amount=amount,
                normalized_span=(offset + label_start, amount_start + len(amount))))
        offset += len(line) + 1
    return matches + _printed_total_matches(lines, blocks)


_PRINTED_TOTAL = re.compile(
    r"^(?P<label>GRAND\s+TOTAL|NET\s+TOTAL(?:\s+ROUNDED)?|TOTAL\s+AMT\s+ROUNDED|"
    r"TOTAL\s+AFTER\s+ADJ(?:USTMENT)?\s+INCL\.?\s+GST|"
    r"(?:TOTAL\s+(?:SALES\s*)?)?INCL(?:\.|USIVE|UDING)?(?:\s+OF)?\s*"
    r"(?:[0-9.]+\s*%?\s*)?(?:GST|TAX)(?:\s*@\s*[0-9.]+\s*%)?|"
    r"TOTAL(?:\s+(?:AMOUNT|AMT|PAYABLE))?|AMOUNT\s+DUE)(?=$|[\s:(：])", re.I)


def _same_row_totals(lines: Sequence[str], blocks: Sequence[dict], index: int,
        kind: str, offset: int) -> list[LabeledAmountMatch]:
    label_box = blocks[index]["box"]
    label_y = sum(point[1] for point in label_box) / len(label_box)
    label_height = max(point[1] for point in label_box) - min(point[1] for point in label_box)
    matches = []
    for other in range(max(0, index - 3), min(len(lines), index + 4)):
        if other == index:
            continue
        parsed = parse_primary_amount_line(lines[other])
        if parsed is None or parsed[0] is not None:
            continue
        box = blocks[other]["box"]
        y = sum(point[1] for point in box) / len(box)
        height = max(point[1] for point in box) - min(point[1] for point in box)
        if abs(y - label_y) <= 0.6 * min(height, label_height):
            other_offset = sum(len(line) + 1 for line in lines[:other])
            matches.append(LabeledAmountMatch(index, kind, parsed[1],
                (min(offset, other_offset), max(offset + len(lines[index]), other_offset + len(lines[other])))))
    return matches


def _printed_total_matches(lines: tuple[str, ...] | list[str], blocks: Sequence[dict] | None) -> list[LabeledAmountMatch]:
    matches = []
    offset = 0
    for index, line in enumerate(lines):
        if re.search(r"(?:GST|TAX)\s+SUMMARY", line, re.I):
            break
        label = _PRINTED_TOTAL.match(line)
        if label:
            matches.extend(_printed_total_line_matches(lines, blocks, index, label, offset))
        offset += len(line) + 1
    return matches


def _printed_total_line_matches(lines, blocks, index, label, offset) -> list[LabeledAmountMatch]:
    # Total/RM/value can occupy three OCR blocks; nearby cash or tax cannot.
    kind = "rounded_total" if re.search(r"ROUNDED|AFTER\s+ADJ", label["label"], re.I) else "total" if label["label"].upper() == "TOTAL" else "final_total"
    tail = lines[index][label.end():].strip(" :：")
    tail = re.sub(r"^\(?(?:RM|MYR)\s*\)?\s*[:：]?\s*", "", tail, flags=re.I)
    parsed = _read_amount_token(tail)
    if tail and (parsed is None or parsed[1].strip(" :：")) and not re.fullmatch(r"\(\d+\)", tail):
        return []  # TOTAL QUANTITY / TOTAL INCLUDES TAX are not totals owed.
    if blocks and not parsed:
        same_row = _same_row_totals(lines, blocks, index, kind, offset)
        if same_row:
            return same_row
    if not blocks and not tail and index and re.match(r"^(?:RM|MYR)\s*\d", lines[index - 1], re.I):
        return []  # Flattened text cannot bind money on either side of this label.
    return _following_total_amount(lines, index, kind, offset, tail)


def _following_total_amount(lines, index, kind, offset, tail) -> list[LabeledAmountMatch]:
    money_start = offset + len(lines[index]) - len(tail)
    for following in range(index + 1, min(index + 3, len(lines))):
        if tail:
            break
        tail = _strip_currency_prefix(lines[following]).strip(" :：()")
        money_start = offset + sum(len(value) + 1 for value in lines[index:following]) + len(lines[following]) - len(tail)
    parsed = _read_amount_token(tail)
    if parsed and not parsed[1].strip(" :："):
        return [LabeledAmountMatch(index, kind, parsed[0], (offset, money_start + len(parsed[0])))]
    return []


def iter_labeled_merchant_matches(lines: tuple[str, ...] | list[str],
        blocks: Sequence[dict] | None = None) -> list[LabeledMerchantMatch]:
    matches: list[LabeledMerchantMatch] = []
    for line_index, line in enumerate(lines):
        stripped = line.strip()
        if stripped in MERCHANT_IGNORED_LINES:
            continue
        for label in sorted(MERCHANT_LABELS, key=len, reverse=True):
            if not stripped.startswith(label):
                continue
            tail = stripped[len(label) :]
            if tail and not (tail[0].isspace() or tail[0] in ":："):
                break
            value = tail.lstrip()
            if value.startswith((":", "：")):
                value = value[1:].lstrip()
            value_index = line_index
            if not value:
                value_index = related_value_index(lines, blocks, line_index)
                if value_index is None:
                    break
                value = lines[value_index].strip()
            value = _merchant_label_value(value)
            if 2 <= len(value) <= 60:
                start = sum(len(item) + 1 for item in lines[:value_index]) + lines[value_index].find(value)
                label_start = sum(len(item) + 1 for item in lines[:line_index])
                matches.append(
                    LabeledMerchantMatch(line_index=line_index, label=label, value=value,
                        value_span=(start, start + len(value)), label_span=(label_start, label_start + len(label)))
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
    for prefix in _CURRENCY_PREFIXES:
        if tail.upper().startswith(prefix.upper()):
            remainder = tail[len(prefix):]
            if prefix[-1].isascii() and prefix[-1].isalpha() and remainder and remainder[0].isalpha():
                continue
            return remainder.lstrip(" :：")
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
    if len(parts) == 2 and not parts[1].isdigit():
        return None
    if index < len(text) and text[index] in ".,0123456789":
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
    "退款成功",
    "还款成功",
    "收款成功",
    "支付失败",
    "付款失败",
    "交易失败",
    "正在付款中...",
    "正在支付中...",
    "账单详情",
    "账单详情>",
    "全部账单",
    *TRANSACTION_SUCCESS_KEYWORDS,
    "交易状态",
    "查看账单详情",
    "查看详情",
    "返回商家",
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
