"""Keep the original capture visible while using the shared funds form."""
from urllib.parse import urlencode

from app.services.debt_service._repayment_draft import get_repayment_draft_response


def capture_context(db, auth, public_id, account):
    if not public_id:
        return None, {}
    capture = get_repayment_draft_response(db, tenant_id=auth.ledger_id,
        actor_account_id=auth.account_id, public_id=public_id)
    defaults = {"source_repayment_draft_id": capture.public_id, "source_amount_basis": "payer_total",
        "source_review_reason": "", "note": capture.merchant_label or "核对通知还款",
        "kind": "credit", "occurred_on": str(capture.accounting_time.accounting_date)
            if capture.accounting_time and capture.accounting_time.accounting_date else ""}
    defaults["task_id"] = f"capture:{capture.public_id}:{account.public_id if account else 'create'}"
    return capture, defaults


def funds_result_href(values: dict, ledger_id: str, account_id: str) -> str:
    query = {"ledger_id": ledger_id, "account_id": account_id}
    if values.get("source_repayment_draft_id"):
        query["source_repayment_draft_id"] = values["source_repayment_draft_id"]
        if values.get("mode") == "create":
            query.pop("account_id")
    return "/web/funds?" + urlencode(query)
