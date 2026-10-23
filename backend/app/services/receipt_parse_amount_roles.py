"""Bind each amount to its own label before considering a receipt's ranking."""

from __future__ import annotations

import re
from dataclasses import replace

from app.services.receipt_parse_common import _AmountCandidate
from app.services.receipt_parse_rules import (
    _PRINTED_TOTAL,
    CURRENCY_AMOUNT_PATTERN,
    CURRENCY_PREFIX_PATTERN,
    TRANSACTION_SUCCESS_KEYWORDS,
)
from app.services.receipt_parse_structure import promotion_start

_LABELS = {
    "payment": ("实付金额", "支付金额", "付款金额", "交易金额", "实付", "实际支付", "实际付款"),
    "expense": ("消费金额", "支出金额", "消费", "支出", "扣款"),
    "total": ("合计", "总计"),
    "order": ("订单金额", "应付金额", "应付"),
    "balance": ("账户余额", "可用余额", "余额", "可用额度", "额度"),
    "discount": ("优惠金额", "优惠", "立减", "红包", "抵扣", "折扣"),
    "repayment": ("还款金额", "还款", "偿还", "归还欠款"),
    "refund": ("退款金额", "退款", "退回"),
    "income": ("收款金额", "收款", "收入", "转入"),
    "fee": ("服务费", "包装费", "配送费", "税额", "找零"),
    "original_price": ("商品原价", "商品总价", "原价"),
    "period_summary": ("本月支出", "本月消费", "累计支出"),
}
_ROLE_BY_LABEL = {label: role for role, labels in _LABELS.items() for label in labels}
_LABEL = re.compile("|".join(re.escape(label) for label in sorted(_ROLE_BY_LABEL, key=len, reverse=True)))
_BRIDGE = re.compile(r"(?:的|已|成功|" + CURRENCY_PREFIX_PATTERN + r"|金额|合计|为|共|[:：\s])*", re.I)
_UNFINISHED = re.compile(
    r"^(?:交易状态[:：\s]*)?(?:(?:支付|付款|交易)(?:失败|关闭|取消|处理中)|"
    r"正在(?:付款|支付)中|待付款|待支付|未付款|未支付|确认支付)|(?:将于|预计).{0,48}(?:扣款|支付)", re.M)
_EVENTS = {"repayment": re.compile(r"^(?:还款成功|已还款|还款完成|已还清|偿还成功)", re.M),
    "refund": re.compile(r"^(?:退款成功|已退款|退款完成|CREDIT\s+NOTE\b|REFUND\s+(?:COMPLETED|SUCCESSFUL)\b)", re.M | re.I),
    "income": re.compile(r"^(?:收款成功|收款到账|收入到账)", re.M),
    "expense": re.compile(r"^(?:交易成功|支付成功|付款成功|自动扣款成功|扣款成功)", re.M)}

AMOUNT_ROLE_PRIORITY = {"rounded_total": 3, "payment": 2, "expense": 2, "final_total": 2, "total": 1, "unknown": 0}


def _role(text: str, start: int, end: int) -> str:
    number = re.search(r"\d", text[start:end])
    money_start = start + number.start() if number else start
    prefix = text[max(0, money_start - 64):money_start]
    labels = list(_LABEL.finditer(prefix))
    if labels and _BRIDGE.fullmatch(prefix[labels[-1].end():]):
        return _ROLE_BY_LABEL[labels[-1].group()]
    suffix = text[end:end + 32]
    label = _LABEL.search(suffix)
    if label and "\n" not in suffix[:label.start()] and _BRIDGE.fullmatch(suffix[:label.start()]):
        return _ROLE_BY_LABEL[label.group()]
    return "unknown"


def _transaction_review_reason(text: str) -> str | None:
    kinds = {kind for kind, pattern in _EVENTS.items() if pattern.search(text)}
    if _UNFINISHED.search(text):
        return "transaction_not_completed"
    if len(kinds) > 1:
        return "conflicting_transaction_kinds"
    if kinds and kinds != {"expense"}:
        return f"{next(iter(kinds))}_receipt"
    return None


def _unlabeled_review_reason(text: str, item: _AmountCandidate, *, has_total: bool) -> str | None:
    if has_total:
        return "unlabeled_amount_beside_total"
    if "signed_primary_amount" in item.evidence and not any(word in text for word in TRANSACTION_SUCCESS_KEYWORDS):
        return "unlabeled_negative_amount"
    return None


def bind_amount_roles(text: str, candidates: list[_AmountCandidate]) -> list[_AmountCandidate]:
    reason = _transaction_review_reason(text)
    promotion = promotion_start(text)
    has_total = any(_PRINTED_TOTAL.match(line) for line in text.splitlines())
    unresolved_rounding = bool(re.search(r"ROUNDING\s+ADJ", text, re.I)) and not any(
        item.role == "rounded_total" for item in candidates)
    if unresolved_rounding:
        reason = reason or "rounding_total_unresolved"
    return [_bind_amount_role(text, item, reason=reason, promotion=promotion, has_total=has_total) for item in candidates]


def _bind_amount_role(text: str, item: _AmountCandidate, *, reason: str | None,
        promotion: int | None, has_total: bool) -> _AmountCandidate:
    role = item.role if item.role != "unknown" else _role(text, *item.normalized_span)
    label_span = _total_remainder_label(text, item) if role == "unknown" else None
    if label_span is not None:
        role = "total"
    if promotion is not None and item.normalized_span[0] >= promotion:
        reason = reason or "promotion_amount"
    if role == "unknown":
        reason = reason or _unlabeled_review_reason(text, item, has_total=has_total)
    return replace(item, role=role, review_reason=reason, label_span=label_span,
        score=max(1, item.score) if role in AMOUNT_ROLE_PRIORITY and role != "unknown" else item.score)


def _total_remainder_label(text: str, candidate: _AmountCandidate) -> tuple[int, int] | None:
    """A total row may contain an explicitly labeled saving and one other price."""
    start, end = candidate.normalized_span
    row_start = text.rfind("\n", 0, start) + 1
    row_end = text.find("\n", end)
    row = text[row_start:row_end if row_end >= 0 else len(text)]
    amounts = list(CURRENCY_AMOUNT_PATTERN.finditer(row))
    if len(amounts) != 2 or not re.fullmatch(r"(?:已优惠|共减|优惠)\s*", row[:amounts[0].start()]):
        return None
    if not (start <= row_start + amounts[1].start() < end):
        return None
    previous_start = text.rfind("\n", 0, max(0, row_start - 1)) + 1
    previous = text[previous_start:row_start].strip()
    if re.fullmatch(r"(?:合计|总计)[\s①-⑳]*", previous):
        return previous_start, previous_start + len(previous)
    return None
