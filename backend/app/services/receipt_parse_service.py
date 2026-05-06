from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.services.category_service import normalize_category
from app.services.time_service import ensure_utc


AMOUNT_PATTERNS = [
    re.compile(
        r"(?:交易金额|支付金额|实付金额|订单金额|消费金额|付款金额|支出金额|金额|实付|合计|总计)"
        r"\s*[:：]?\s*(?:人民币|RMB|CNY|¥|￥)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:支出|付款|支付|消费)\s*(?:人民币|RMB|CNY|¥|￥)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE),
    re.compile(r"(?:¥|￥)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"),
    re.compile(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:元|人民币)"),
]

PRIMARY_AMOUNT_LINE_PATTERN = re.compile(
    r"^(?P<sign>[-−﹣－])?\s*(?:人民币|RMB|CNY|¥|￥)?\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:元|人民币)?$",
    re.IGNORECASE,
)

TRANSACTION_SUCCESS_KEYWORDS = ["交易成功", "支付成功", "付款成功"]
DISCOUNT_AMOUNT_LABELS = ["优惠", "立减", "红包", "券", "奖励", "抵扣"]

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

MERCHANT_KEYWORDS = [
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
]

BANK_KEYWORDS = [
    "中国建设银行",
    "招商银行",
    "工商银行",
    "农业银行",
    "中国银行",
    "交通银行",
    "邮储银行",
]

MERCHANT_IGNORED_LINES = {
    "账单详情",
    "全部账单",
    "交易成功",
    "支付成功",
    "付款成功",
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

MERCHANT_LABEL_PATTERN = re.compile(
    r"(?:商家|收款方全称|收款方|付款给|对方户名|交易对象|店铺|门店|平台|应用|来源)\s*[:：]?\s*([^\n\r，,。；;]{2,60})"
)


@dataclass(frozen=True)
class ParsedReceipt:
    amount_cents: int | None = None
    merchant: str | None = None
    expense_time: datetime | None = None
    category: str | None = None
    confidence: float | None = None


def parse_receipt_text(raw_text: str) -> ParsedReceipt:
    text = _normalize_text(raw_text)
    if not text:
        return ParsedReceipt()

    amount_cents = _extract_amount_cents(text)
    merchant = _extract_merchant(text)
    expense_time = _extract_expense_time(text)
    category = _suggest_category(text, merchant)
    confidence = _estimate_confidence(
        amount_cents=amount_cents,
        merchant=merchant,
        expense_time=expense_time,
        raw_text=text,
    )

    return ParsedReceipt(
        amount_cents=amount_cents,
        merchant=merchant,
        expense_time=expense_time,
        category=category,
        confidence=confidence,
    )


def _normalize_text(raw_text: str) -> str:
    return "\n".join(line.strip() for line in raw_text.replace("\r", "\n").splitlines() if line.strip())


def _extract_amount_cents(text: str) -> int | None:
    primary_amount = _extract_primary_transaction_amount_cents(text)
    if primary_amount is not None:
        return primary_amount

    candidates: list[int] = []
    for pattern in AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            cents = _money_to_cents(match.group(1))
            if cents is not None and 0 < cents < 10_000_000_00:
                candidates.append(cents)
        if candidates:
            return candidates[0]
    return None


def _extract_primary_transaction_amount_cents(text: str) -> int | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = PRIMARY_AMOUNT_LINE_PATTERN.match(line.strip())
        if not match:
            continue

        # In Alipay detail pages the real paid amount is often the large signed
        # amount immediately above "交易成功". Labeled amounts like "订单金额"
        # include discounts and should be a fallback only.
        if not match.group("sign"):
            continue

        nearby = "\n".join(lines[max(0, index - 2) : min(len(lines), index + 3)])
        if not any(keyword in nearby for keyword in TRANSACTION_SUCCESS_KEYWORDS):
            continue

        previous = lines[index - 1] if index > 0 else ""
        if any(label in previous for label in DISCOUNT_AMOUNT_LABELS):
            continue

        cents = _money_to_cents(match.group("amount"))
        if cents is not None and 0 < cents < 10_000_000_00:
            return cents
    return None


def _money_to_cents(value: str) -> int | None:
    try:
        amount = Decimal(value.replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    cents = (amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _extract_merchant(text: str) -> str | None:
    title_merchant = _extract_transaction_title_merchant(text)
    if title_merchant:
        return title_merchant

    labeled = MERCHANT_LABEL_PATTERN.search(text)
    if labeled:
        return _clean_merchant(labeled.group(1))

    for keyword in MERCHANT_KEYWORDS:
        if keyword in BANK_KEYWORDS and _looks_like_payment_institution_context(text, keyword):
            continue
        if keyword.lower() in text.lower():
            return keyword

    first_line = text.splitlines()[0].strip()
    if 2 <= len(first_line) <= 30 and not any(ch.isdigit() for ch in first_line):
        return _clean_merchant(first_line)
    return None


def _extract_transaction_title_merchant(text: str) -> str | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not any(keyword in line for keyword in TRANSACTION_SUCCESS_KEYWORDS):
            continue

        for candidate in reversed(lines[max(0, index - 5) : index]):
            cleaned = _clean_merchant(candidate)
            if _is_title_merchant_candidate(cleaned):
                return cleaned
    return None


def _is_title_merchant_candidate(value: str | None) -> bool:
    if not value:
        return False
    if value in MERCHANT_IGNORED_LINES:
        return False
    if PRIMARY_AMOUNT_LINE_PATTERN.match(value):
        return False
    if len(value) < 2 or len(value) > 30:
        return False
    if any(label in value for label in ["金额", "时间", "方式", "订单", "机构", "奖励"]):
        return False
    return True


def _looks_like_payment_institution_context(text: str, keyword: str) -> bool:
    if keyword not in text:
        return False
    if "交易提醒" in text and text.splitlines()[0].strip() == keyword:
        return False
    return any(label in text for label in ["收单机构", "清算机构", "收款方全称"])


def _clean_merchant(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip(" ：:，,。；;")
    return cleaned or None


def _extract_expense_time(text: str) -> datetime | None:
    for pattern in TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        year, month, day, hour, minute, second = match.groups()
        try:
            local_value = datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                int(second or 0),
                tzinfo=_default_timezone(),
            )
        except ValueError:
            continue
        return ensure_utc(local_value)
    return None


def _default_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().ocr_default_timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


def _suggest_category(text: str, merchant: str | None) -> str | None:
    haystack = f"{merchant or ''}\n{text}".lower()
    category_rules = [
        ("餐饮", ["美团", "饿了么", "kfc", "肯德基", "麦当劳", "餐", "外卖", "好想来", "零食", "小吃", "奶茶"]),
        ("购物", ["京东", "淘宝", "天猫", "拼多多", "购物"]),
        ("交通", ["滴滴", "高德", "地铁", "公交", "打车"]),
        ("AI订阅", ["openai", "claude", "gemini", "kimi", "chatgpt"]),
        ("游戏", ["steam", "taptap", "playstation", "任天堂"]),
        ("医疗", ["医院", "药房", "买药"]),
        ("通讯", ["中国移动", "中国联通", "中国电信", "话费"]),
    ]
    for category, keywords in category_rules:
        if any(keyword.lower() in haystack for keyword in keywords):
            return normalize_category(category)
    return None


def _estimate_confidence(
    *,
    amount_cents: int | None,
    merchant: str | None,
    expense_time: datetime | None,
    raw_text: str,
) -> float:
    score = 0.15
    if amount_cents is not None:
        score += 0.35
    if merchant:
        score += 0.2
    if expense_time is not None:
        score += 0.2
    if len(raw_text) >= 20:
        score += 0.1
    return min(score, 0.95)
