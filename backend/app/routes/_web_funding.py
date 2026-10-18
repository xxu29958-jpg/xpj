"""Translate retained major-unit funding inputs; the command owns all accounting."""
import json

from pydantic import ValidationError

from app.errors import AppError
from app.schemas.funds import FundingPart, RefundDestination
from app.services.currency_common import major_amount_to_minor
from app.services.funds_query import get_account, list_accounts


def funding_options(db, auth):
    return [row.model_dump(mode="json") for row in list_accounts(db, ledger_id=auth.ledger_id,
        actor_account_id=auth.account_id) if not row.archived]


def parse_funding(db, *, ledger_id, actor_account_id, raw, currency_code):
    if actor_account_id is None:
        raise AppError("invalid_token", "请先登录原身份再核对资金来源。", status_code=401)
    try:
        rows = json.loads(raw or "[]")
        if not isinstance(rows, list) or len(rows) > 8:
            raise ValueError("funding_parts")
        parts = []
        for item in rows:
            account = get_account(db, ledger_id=ledger_id, actor_account_id=actor_account_id,
                public_id=item["account_public_id"])
            if account.currency_code != item["account_currency"] or item["expense_currency"] != currency_code:
                raise AppError("state_conflict", "付款组成的原币种已变化，请保留原输入并核对。", status_code=409)
            parts.append(FundingPart(component_id=item["component_id"], account_public_id=account.public_id,
                account_row_version=item["account_row_version"],
                expense_amount_minor=major_amount_to_minor(item["expense_amount"], currency_code),
                account_amount_minor=major_amount_to_minor(item["account_amount"], account.currency_code),
                expense_currency_code=currency_code, account_currency_code=account.currency_code,
                included_in_opening=item.get("included_in_opening", False)))
        return parts
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise AppError("invalid_request", "请核对每项付款的账户、币种和金额。原输入已保留。", status_code=422) from exc


def parse_refund_destinations(db, auth, raw, currency_code):
    return [RefundDestination(account_public_id=part.account_public_id, account_row_version=part.account_row_version,
        original_amount_minor=part.expense_amount_minor, received_amount_minor=part.account_amount_minor)
        for part in parse_funding(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id,
            raw=raw, currency_code=currency_code)] or None


def review_funding_values(db, auth, raw, currency_code):
    parse_funding(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, raw=raw, currency_code=currency_code)
    rows = json.loads(raw or "[]")
    for row in rows:
        account = get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=row["account_public_id"])
        row["account_row_version"] = account.row_version
    return json.dumps(rows, ensure_ascii=False)
