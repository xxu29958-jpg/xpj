from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.services.category_service import normalize_category
from app.services.time_service import ensure_utc


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

TRANSACTION_SUCCESS_KEYWORDS = ["交易成功", "支付成功", "付款成功"]
DISCOUNT_AMOUNT_LABELS = ["优惠", "立减", "红包", "券", "奖励", "抵扣"]
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
SUCCESS_PAGE_AD_KEYWORDS = ["评价", "红包", "扫街榜", "限时", "打车", "高德", "领取", "优惠", "奖励"]
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

MERCHANT_LABEL_PATTERN = re.compile(
    r"(?:^|\n)(?P<label>商家|收款方全称|收款方|付款给|对方户名|交易对象|店铺|门店|平台|应用|来源)"
    r"\s*[:：]?\s*(?P<value>[^\n\r，,。；;]{2,60})"
)


@dataclass(frozen=True)
class ParsedReceipt:
    amount_cents: int | None = None
    merchant: str | None = None
    expense_time: datetime | None = None
    category: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class _AmountCandidate:
    amount_cents: int
    score: int
    line_index: int
    source: str


@dataclass(frozen=True)
class _MerchantCandidate:
    value: str
    score: int
    line_index: int
    source: str


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
    candidates = _amount_candidates(text)
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate.score, -candidate.line_index)).amount_cents


def _amount_candidates(text: str) -> list[_AmountCandidate]:
    lines = text.splitlines()
    candidates: list[_AmountCandidate] = []

    for index, line in enumerate(lines):
        line_text = line.strip()
        match = PRIMARY_AMOUNT_LINE_PATTERN.match(line_text)
        if match:
            cents = _money_to_cents(match.group("amount"))
            if cents is not None and 0 < cents < 10_000_000_00:
                has_money_marker = _has_money_marker(line_text)
                has_nearby_success = _has_nearby_success(lines, index)
                if not (has_money_marker or has_nearby_success or match.group("sign")):
                    continue
                score = 32 if has_money_marker else 24
                if has_nearby_success:
                    score = 90
                if match.group("sign"):
                    score += 12
                if _has_discount_context(lines, index):
                    score -= 50
                if score > 0:
                    candidates.append(_AmountCandidate(cents, score, index, "line"))

    for match in LABELED_AMOUNT_PATTERN.finditer(text):
        cents = _money_to_cents(match.group("amount"))
        if cents is None or not 0 < cents < 10_000_000_00:
            continue
        label = match.group("label")
        index = _line_index_for_offset(text, match.start())
        score = {
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
        }.get(label, 35)
        if _has_discount_context(lines, index):
            score -= 45
        candidates.append(_AmountCandidate(cents, score, index, f"label:{label}"))

    for pattern, source, base_score in [
        (CURRENCY_AMOUNT_PATTERN, "currency", 28),
        (YUAN_AMOUNT_PATTERN, "yuan", 22),
    ]:
        for match in pattern.finditer(text):
            cents = _money_to_cents(match.group("amount"))
            if cents is None or not 0 < cents < 10_000_000_00:
                continue
            index = _line_index_for_offset(text, match.start())
            score = base_score + (42 if _has_nearby_success(lines, index) else 0)
            if _has_discount_context(lines, index):
                score -= 45
            if score > 0:
                candidates.append(_AmountCandidate(cents, score, index, source))

    return candidates


def _line_index_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset)


def _has_nearby_success(lines: list[str], index: int) -> bool:
    nearby = "\n".join(lines[max(0, index - 2) : min(len(lines), index + 3)])
    return any(keyword in nearby for keyword in TRANSACTION_SUCCESS_KEYWORDS)


def _has_discount_context(lines: list[str], index: int) -> bool:
    nearby = "\n".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
    return any(label in nearby for label in DISCOUNT_AMOUNT_LABELS)


def _has_money_marker(value: str) -> bool:
    upper_value = value.upper()
    return any(marker in value for marker in ["¥", "￥", "元", "人民币"]) or any(
        marker in upper_value for marker in ["RMB", "CNY"]
    )


def _money_to_cents(value: str) -> int | None:
    try:
        amount = Decimal(value.replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    cents = (amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _extract_merchant(text: str) -> str | None:
    candidates = _merchant_candidates(text)
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate.score, -candidate.line_index)).value


def _merchant_candidates(text: str) -> list[_MerchantCandidate]:
    lines = text.splitlines()
    candidates: list[_MerchantCandidate] = []

    for index, line in enumerate(lines):
        if not any(keyword in line for keyword in TRANSACTION_SUCCESS_KEYWORDS):
            continue

        for candidate_index in range(index - 1, max(-1, index - 6), -1):
            cleaned = _clean_merchant(lines[candidate_index])
            candidate = _score_merchant_candidate(
                text=text,
                value=cleaned,
                base_score=100,
                line_index=candidate_index,
                source="success_title",
                require_no_digits=False,
            )
            if candidate:
                candidates.append(candidate)
                break

        if line.strip() == "支付成功":
            for candidate_index in range(index + 1, min(len(lines), index + 10)):
                cleaned = _clean_merchant(lines[candidate_index])
                candidate = _score_merchant_candidate(
                    text=text,
                    value=cleaned,
                    base_score=90,
                    line_index=candidate_index,
                    source="success_body",
                    require_no_digits=True,
                )
                if candidate:
                    candidates.append(candidate)
                    break

    for index, line in enumerate(lines):
        if not PAYMENT_METHOD_LINE_PATTERN.match(line.strip()):
            continue
        for candidate_index in range(index - 1, max(-1, index - 4), -1):
            cleaned = _clean_merchant(lines[candidate_index])
            candidate = _score_merchant_candidate(
                text=text,
                value=cleaned,
                base_score=86,
                line_index=candidate_index,
                source="payment_method_previous_line",
                require_no_digits=False,
            )
            if candidate:
                candidates.append(candidate)
                break

    for match in MERCHANT_LABEL_PATTERN.finditer(text):
        cleaned = _clean_merchant(match.group("value"))
        label = match.group("label")
        index = _line_index_for_offset(text, match.start())
        base_score = {
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
        }.get(label, 50)
        candidate = _score_merchant_candidate(
            text=text,
            value=cleaned,
            base_score=base_score,
            line_index=index,
            source=f"label:{label}",
            require_no_digits=False,
        )
        if candidate:
            candidates.append(candidate)

    lower_text = text.lower()
    for keyword in MERCHANT_KEYWORDS:
        if keyword.lower() not in lower_text:
            continue
        base_score = 80 if _looks_like_bank_reminder(text, keyword) else 45
        candidate = _score_merchant_candidate(
            text=text,
            value=keyword,
            base_score=base_score,
            line_index=_line_index_for_offset(lower_text, lower_text.find(keyword.lower())),
            source="keyword",
            require_no_digits=False,
        )
        if candidate:
            candidates.append(candidate)

    first_line = text.splitlines()[0].strip()
    candidate = _score_merchant_candidate(
        text=text,
        value=_clean_merchant(first_line),
        base_score=35,
        line_index=0,
        source="first_line",
        require_no_digits=True,
    )
    if candidate:
        candidates.append(candidate)

    return candidates


def _score_merchant_candidate(
    *,
    text: str,
    value: str | None,
    base_score: int,
    line_index: int,
    source: str,
    require_no_digits: bool,
) -> _MerchantCandidate | None:
    if not _is_title_merchant_candidate(value):
        return None
    assert value is not None
    if require_no_digits and any(ch.isdigit() for ch in value):
        return None

    score = base_score
    if source != "keyword" and any(keyword in value for keyword in SUCCESS_PAGE_AD_KEYWORDS):
        score -= 60
    if value in SUCCESS_PAGE_SKIP_LINES:
        score -= 70
    if value in BANK_KEYWORDS and _looks_like_payment_institution_context(text, value):
        score -= 65
    if len(value) > 24 and source == "success_body":
        score -= 45
    if score < 25:
        return None
    return _MerchantCandidate(value=value, score=score, line_index=line_index, source=source)


def _is_title_merchant_candidate(value: str | None) -> bool:
    if not value:
        return False
    if value in MERCHANT_IGNORED_LINES:
        return False
    if PRIMARY_AMOUNT_LINE_PATTERN.match(value):
        return False
    if len(value) < 2 or len(value) > 30:
        return False
    upper_value = value.upper()
    if CLOCK_LINE_PATTERN.match(value) or "4G" in upper_value or "5G" in upper_value or "WIFI" in upper_value:
        return False
    if any(label in value for label in ["金额", "时间", "方式", "订单", "机构", "奖励", "支付"]):
        return False
    return True


def _looks_like_payment_institution_context(text: str, keyword: str) -> bool:
    if keyword not in text:
        return False
    if "交易提醒" in text and text.splitlines()[0].strip() == keyword:
        return False
    return any(label in text for label in ["收单机构", "清算机构", "收款方全称"])


def _looks_like_bank_reminder(text: str, keyword: str) -> bool:
    lines = text.splitlines()
    return keyword in BANK_KEYWORDS and bool(lines) and lines[0].strip() == keyword and "交易提醒" in text


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
    merchant_text = (merchant or "").lower()
    full_text = f"{merchant or ''}\n{text}".lower()
    category_rules = [
        ("餐饮", ["美团", "饿了么", "kfc", "肯德基", "麦当劳", "餐", "外卖", "好想来", "零食", "小吃", "奶茶", "罗森", "便利店"]),
        ("购物", ["京东", "淘宝", "天猫", "拼多多", "购物", "超市", "批发", "商超"]),
        ("交通", ["滴滴", "高德", "地铁", "公交", "打车"]),
        ("AI订阅", ["openai", "claude", "gemini", "kimi", "chatgpt"]),
        ("游戏", ["steam", "taptap", "playstation", "任天堂"]),
        ("医疗", ["医院", "药房", "买药"]),
        ("通讯", ["中国移动", "中国联通", "中国电信", "话费"]),
    ]
    for category, keywords in category_rules:
        if merchant_text and any(keyword.lower() in merchant_text for keyword in keywords):
            return normalize_category(category)
    for category, keywords in category_rules:
        if any(keyword.lower() in full_text for keyword in keywords):
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
