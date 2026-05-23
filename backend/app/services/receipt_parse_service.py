from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.services.receipt_parse_amount import (
    _amount_candidates,
    _calibrate_amount_candidates,
)
from app.services.receipt_parse_category import (
    _calibrate_category_candidates,
    _category_candidates,
)
from app.services.receipt_parse_common import (
    ParsedReceipt,
    ParsedReceiptItem,
    _AmountCandidate,
    _best_candidate,
    _build_receipt_context,
    _CategoryCandidate,
    _MerchantCandidate,
    _normalize_text,
    _ReceiptContext,
    _score_ratio,
    _TimeCandidate,
)
from app.services.receipt_parse_merchant import (
    _calibrate_merchant_candidates,
    _merchant_candidates,
)
from app.services.receipt_parse_rules import CATEGORY_HINT_RULES
from app.services.receipt_parse_time import (
    _calibrate_time_candidates,
    _time_candidates,
)

ITEM_LINE_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z一-鿿][A-Za-z0-9一-鿿（）()·+\-/&\s]{0,80}?)"
    r"(?:\s+(?P<quantity>(?:[xX×]\s*)?\d+(?:\.\d+)?\s*(?:份|杯|个|件|盒|袋|瓶|包|次|斤|克|kg|g)?))?"
    r"\s+(?:¥|￥)?(?P<amount>-?[0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:元)?$"
)

# ADR-0035: line item kind identifiers. Order matters within classify —
# discount keywords run before _SUMMARY_KEYWORDS so "优惠" routes to
# kind=discount, not to noise-skip.
_DISCOUNT_KEYWORDS = (
    "优惠",
    "立减",
    "满减",
    "红包",
    "抵扣",
    "折扣",
    "VIP折",
    "折后",
    "促销减",
    "券",
)
_TAX_KEYWORDS = (
    "税额",
    "增值税",
    "消费税",
    "VAT",
    "GST",
    "Tax",
)
_SERVICE_FEE_KEYWORDS = (
    "服务费",
    "茶位费",
    "包装费",
    "餐位费",
    "配送费",
    "外卖费",
)
# Pure summary / non-item lines that should be skipped entirely.
ITEM_NOISE_KEYWORDS = (
    "交易",
    "支付",
    "付款",
    "消费",
    "订单",
    "金额",
    "合计",
    "总计",
    "实付",
    "应付",
    "奖励",
    "找零",
    "收款",
    "付款方式",
    "支付方式",
    "银行卡",
    "储蓄卡",
    "信用卡",
    "尾号",
    "交易时间",
    "支付时间",
    "创建时间",
    "下单时间",
    "订单号",
    "商家订单号",
    "账单详情",
    "交易提醒",
    "动账提醒",
)


def _estimate_confidence(
    *,
    context: _ReceiptContext,
    amount_candidate: _AmountCandidate | None,
    merchant_candidate: _MerchantCandidate | None,
    time_candidate: _TimeCandidate | None,
    category_candidate: _CategoryCandidate | None,
    raw_text: str,
) -> float:
    score = 0.12
    if amount_candidate is not None:
        score += 0.35 * _score_ratio(amount_candidate.score)
    if merchant_candidate is not None:
        score += 0.22 * _score_ratio(merchant_candidate.score)
    if time_candidate is not None:
        score += 0.2 * _score_ratio(time_candidate.score)
    if category_candidate is not None:
        score += 0.06 * _score_ratio(category_candidate.score)
    if len(raw_text) >= 20:
        score += 0.06
    score += _context_quality_bonus(
        context=context,
        amount_candidate=amount_candidate,
        merchant_candidate=merchant_candidate,
        time_candidate=time_candidate,
    )
    return round(min(score, 0.95), 4)


def _context_quality_bonus(
    *,
    context: _ReceiptContext,
    amount_candidate: _AmountCandidate | None,
    merchant_candidate: _MerchantCandidate | None,
    time_candidate: _TimeCandidate | None,
) -> float:
    signals = context.signals
    bonus = 0.0
    if context.profile != "generic":
        bonus += 0.03
    if signals.structured_signal_count >= 3:
        bonus += 0.03
    if signals.structured_signal_count >= 5:
        bonus += 0.02
    if amount_candidate is not None and merchant_candidate is not None:
        bonus += 0.03
    if amount_candidate is not None and time_candidate is not None:
        bonus += 0.02
    if signals.discount_marker_count and context.profile == "alipay_bill_detail":
        bonus += 0.01
    if signals.line_count < 3:
        bonus -= 0.04
    return max(-0.08, min(bonus, 0.11))


def _parse_receipt_items(
    context: _ReceiptContext, parent_amount_cents: int | None
) -> tuple[ParsedReceiptItem, ...]:
    if context.profile == "bank_reminder":
        return ()

    items: list[ParsedReceiptItem] = []
    for line in context.lines:
        item = _parse_receipt_item_line(line)
        if item is not None:
            items.append(item)

    if len(items) < 2:
        return ()

    item_total = sum(item.amount_cents or 0 for item in items)
    if parent_amount_cents is not None and item_total > max(parent_amount_cents * 3, parent_amount_cents + 50_000):
        return ()
    return tuple(items[:200])


_DISCOUNT_PATTERNS = (
    # "满100减10" / "满 100 减 5" promotional rule expressions.
    # 不直接把单字 "减" 加入 _DISCOUNT_KEYWORDS 以避免误判商品名"减肥茶"。
    re.compile(r"满\s*\d+\s*减\s*\d*"),
)


def _classify_item_kind(line: str) -> str:
    """Pick line item kind by keyword. Default 'product'."""
    # discount 优先：现实"VIP优惠"既含"优惠"也是折扣行，必须走 discount
    if any(kw in line for kw in _DISCOUNT_KEYWORDS):
        return "discount"
    if any(pat.search(line) for pat in _DISCOUNT_PATTERNS):
        return "discount"
    if any(kw in line for kw in _SERVICE_FEE_KEYWORDS):
        return "service_fee"
    if any(kw in line for kw in _TAX_KEYWORDS):
        return "tax"
    return "product"


def _parse_receipt_item_line(line: str) -> ParsedReceiptItem | None:
    cleaned = " ".join(line.strip().split())
    if not cleaned or any(keyword in cleaned for keyword in ITEM_NOISE_KEYWORDS):
        return None
    match = ITEM_LINE_PATTERN.match(cleaned)
    if not match:
        return None

    amount_cents = _item_money_to_cents(match.group("amount"))
    if amount_cents is None:
        return None

    kind = _classify_item_kind(cleaned)
    # Normalize amount sign by kind (ADR-0035): discount lines must be ≤ 0,
    # all others ≥ 0. Real OCR may emit "VIP优惠 3.00" (positive amount
    # but discount semantically) or "VIP优惠 -3.00" (negative); both
    # should land as discount with amount_cents <= 0.
    if kind == "discount":
        amount_cents = -abs(amount_cents)
        if amount_cents == 0:
            return None
    else:
        if amount_cents <= 0:
            return None

    name = _clean_item_name(match.group("name"))
    if name is None:
        return None

    quantity_text = _clean_item_quantity(match.group("quantity"))
    # Discount / tax / service_fee don't have unit prices; suppress to avoid
    # nonsensical "VIP 优惠 unit_price -3.00" UI rendering.
    unit_price = (
        _item_unit_price_cents(amount_cents, quantity_text)
        if kind == "product"
        else None
    )
    return ParsedReceiptItem(
        name=name,
        quantity_text=quantity_text,
        amount_cents=amount_cents,
        unit_price_cents=unit_price,
        category=_category_for_item_name(name) if kind == "product" else None,
        raw_text=cleaned,
        confidence=0.72,
        kind=kind,
    )


def _clean_item_name(value: str) -> str | None:
    cleaned = value.strip(" \t:-：")
    if len(cleaned) < 2 or len(cleaned) > 80:
        return None
    if cleaned.isdigit():
        return None
    return cleaned


def _clean_item_quantity(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.replace("×", "x").strip()
    return cleaned or None


def _item_quantity_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value.replace("×", "x"))
    if not match:
        return None
    try:
        quantity = Decimal(match.group(0))
    except InvalidOperation:
        return None
    if quantity <= 0:
        return None
    return quantity


def _item_unit_price_cents(amount_cents: int, quantity_text: str | None) -> int | None:
    quantity = _item_quantity_decimal(quantity_text)
    if quantity is None:
        return None
    return int((Decimal(amount_cents) / quantity).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _category_for_item_name(name: str) -> str | None:
    lowered = name.casefold()
    for rule in CATEGORY_HINT_RULES:
        if any(keyword.casefold() in lowered for keyword in rule.keywords):
            return rule.category
    return None


def _item_money_to_cents(value: str) -> int | None:
    try:
        amount = Decimal(value.replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    cents = (amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def parse_receipt_text(
    raw_text: str, timezone_name: str | None = None
) -> ParsedReceipt:
    text = _normalize_text(raw_text)
    if not text:
        return ParsedReceipt()

    context = _build_receipt_context(text)
    amount_candidate = _best_candidate(
        _calibrate_amount_candidates(_amount_candidates(text), context)
    )
    merchant_candidate = _best_candidate(
        _calibrate_merchant_candidates(_merchant_candidates(text), context)
    )
    time_candidate = _best_candidate(
        _calibrate_time_candidates(_time_candidates(text, timezone_name), context)
    )
    amount_cents = amount_candidate.amount_cents if amount_candidate else None
    merchant = merchant_candidate.value if merchant_candidate else None
    expense_time = time_candidate.value if time_candidate else None
    category_candidate = _best_candidate(
        _calibrate_category_candidates(
            _category_candidates(text, merchant), context, merchant_candidate
        )
    )
    category = category_candidate.category if category_candidate else None
    confidence = _estimate_confidence(
        context=context,
        amount_candidate=amount_candidate,
        merchant_candidate=merchant_candidate,
        time_candidate=time_candidate,
        category_candidate=category_candidate,
        raw_text=text,
    )
    items = _parse_receipt_items(context, amount_cents)

    return ParsedReceipt(
        amount_cents=amount_cents,
        merchant=merchant,
        expense_time=expense_time,
        category=category,
        confidence=confidence,
        items=items,
    )
