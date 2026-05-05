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

MERCHANT_LABEL_PATTERN = re.compile(
    r"(?:商家|收款方|付款给|对方户名|交易对象|店铺|门店|平台|应用|来源)\s*[:：]\s*([^\n\r，,。；;]{2,40})"
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
    candidates: list[int] = []
    for pattern in AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            cents = _money_to_cents(match.group(1))
            if cents is not None and 0 < cents < 10_000_000_00:
                candidates.append(cents)
        if candidates:
            return candidates[0]
    return None


def _money_to_cents(value: str) -> int | None:
    try:
        amount = Decimal(value.replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    cents = (amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _extract_merchant(text: str) -> str | None:
    labeled = MERCHANT_LABEL_PATTERN.search(text)
    if labeled:
        return _clean_merchant(labeled.group(1))

    for keyword in MERCHANT_KEYWORDS:
        if keyword.lower() in text.lower():
            return keyword

    first_line = text.splitlines()[0].strip()
    if 2 <= len(first_line) <= 30 and not any(ch.isdigit() for ch in first_line):
        return _clean_merchant(first_line)
    return None


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
        ("餐饮", ["美团", "饿了么", "kfc", "肯德基", "麦当劳", "餐", "外卖"]),
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
