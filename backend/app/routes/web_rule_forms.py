"""Rule form values carry the currency selected when the form was opened."""

from app.errors import AppError
from app.services.currency_common import (
    currency_input_metadata,
    major_amount_to_minor,
    minor_amount_label,
    minor_amount_value,
    normalize_currency_code,
)


def rule_amount_label(amount: int | None, currency: str | None) -> str:
    if amount is None:
        return "—"
    try:
        return f"{normalize_currency_code(currency)} {minor_amount_label(amount, currency)}"
    except AppError:
        return f"{amount} 最小单位 · 币种待确认"


def rule_currency_input(currency: str | None) -> dict:
    try:
        return currency_input_metadata(currency)
    except AppError:
        return {}


def parse_rule_amount(raw: str, *, currency_code: str | None) -> int | None:
    if not raw:
        return None
    try:
        return major_amount_to_minor(raw, normalize_currency_code(currency_code))
    except AppError as exc:
        raise AppError("invalid_request", "金额条件或币种无效，输入已保留。", status_code=422) from exc


def parse_rule_form(values: dict[str, str]) -> dict:
    try:
        priority = int(values["priority"])
    except ValueError as exc:
        raise AppError("invalid_request", "优先级必须是整数。", status_code=422) from exc
    currency = values.get("home_currency_code") or None
    raw_min, raw_max = values["amount_min_yuan"], values["amount_max_yuan"]
    if raw_min or raw_max or currency:
        currency = normalize_currency_code(currency)
    return {
        "keyword": values["keyword"], "category": values["category"], "priority": priority,
        "home_currency_code": currency,
        "amount_min_cents": parse_rule_amount(raw_min, currency_code=currency),
        "amount_max_cents": parse_rule_amount(raw_max, currency_code=currency),
        "source_contains": values["source_contains"], "tag_contains": values["tag_contains"],
    }


def rule_edit_values(rule, *, new_currency: str | None) -> dict[str, str]:
    recorded = rule.home_currency_code
    has_amount = rule.amount_min_cents is not None or rule.amount_max_cents is not None
    currency = recorded if has_amount or recorded else new_currency

    def amount_value(amount):
        if amount is None:
            return ""
        return minor_amount_value(amount, recorded) if rule_currency_input(recorded) else str(amount)

    return {
        "keyword": rule.keyword, "category": rule.category, "priority": str(rule.priority),
        "amount_min_yuan": amount_value(rule.amount_min_cents),
        "amount_max_yuan": amount_value(rule.amount_max_cents),
        "source_contains": rule.source_contains or "", "tag_contains": rule.tag_contains or "",
        "home_currency_code": currency or "", "expected_row_version": str(rule.row_version),
    }


def rule_form_currency_matches(rule, values: dict[str, str]) -> bool:
    captured = values.get("home_currency_code") or None
    if rule.home_currency_code:
        return bool(rule_currency_input(captured)) and captured == rule.home_currency_code
    # A previously nonmonetary rule may acquire its first explicit currency.
    if rule.amount_min_cents is not None or rule.amount_max_cents is not None:
        return False
    return not captured or bool(rule_currency_input(captured))
