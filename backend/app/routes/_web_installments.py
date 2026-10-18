"""Retained form values are parsed in the captured account currency."""
import json

from app.schemas.installment import (
    CreditDrawPaymentPart,
    InstallmentCommand,
    InstallmentPaymentPart,
    InstallmentPeriodInput,
)
from app.services.currency_common import major_amount_to_minor, minor_amount_value


def installment_form_values(agreement, currency):
    periods = [{"due_on": str(row.due_on), "principal": minor_amount_value(row.principal_minor - row.paid_principal_minor, currency),
        "fee": minor_amount_value(row.planned_fee_minor - row.paid_fee_minor, currency)}
        for row in agreement.periods if row.principal_minor > row.paid_principal_minor]
    return {"name": agreement.name, "supersedes_public_id": agreement.public_id,
        "draw_ids_json": json.dumps(agreement.draw_public_ids), "periods_json": json.dumps(periods), "opening_source": ""}


def installment_payload(values):
    currency = values["currency_code"]
    return InstallmentCommand(expected_row_version=values["expected_row_version"], name=values["name"],
        source=values["opening_source"], agreed_on=values["occurred_on"],
        supersedes_public_id=values.get("supersedes_public_id") or None, draw_public_ids=json.loads(values["draw_ids_json"]),
        periods=[InstallmentPeriodInput(due_on=row["due_on"], principal_minor=major_amount_to_minor(row["principal"], currency),
            planned_fee_minor=major_amount_to_minor(row["fee"], currency) if row.get("fee", "").strip() else 0)
            for row in json.loads(values["periods_json"])])


def payment_allocations(values):
    currency = values["currency_code"]
    periods, draws = [], []
    for row in json.loads(values.get("allocation_json", "[]")):
        if not row.get("principal", "").strip() and not row.get("fee", "").strip():
            continue
        principal = major_amount_to_minor(row["principal"], currency) if row.get("principal", "").strip() else 0
        if row["kind"] == "period":
            periods.append(InstallmentPaymentPart(period_public_id=row["public_id"], principal_minor=principal,
                fee_minor=major_amount_to_minor(row["fee"], currency) if row.get("fee", "").strip() else 0))
        else:
            draws.append(CreditDrawPaymentPart(draw_public_id=row["public_id"], principal_minor=principal))
    return {"period_allocations": periods, "draw_allocations": draws,
        "overpayment_minor": major_amount_to_minor(values["overpayment"], currency) if values.get("overpayment", "").strip() else 0}
