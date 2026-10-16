"""Real application scheduling and cross-page reads for a manual debt adjustment."""

from scripts.planning_journey_android import wait_for


def adjustment_facts(ledger):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Debt, DebtAdjustment

    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.tenant_id == ledger, Debt.counterparty_label == "T3Loan"))
        if debt is None:
            return None
        adjustments = list(db.scalars(select(DebtAdjustment).where(DebtAdjustment.debt_id == debt.id)))
        return {"public_id": debt.public_id, "principal": debt.principal_amount_cents,
            "version": debt.row_version, "adjustments": [{"id": row.public_id, "amount": row.amount_cents,
                "reason": row.reason, "key": row.idempotency_key} for row in adjustments]}


def manual_adjustment(j):
    page, native, ledger = j.receiver, j.native, j.identity.receiver_ledger
    j.goto("/web/debts/new", receiver=True)
    form = page.locator('form[action="/web/debts"]')
    form.locator('[name="counterparty_label"]').fill("T3Loan")
    form.locator('[name="amount_major"]').fill("50.00")
    page.locator('button[form="debt-creation"][data-debtcreation-submit]').click()
    original = wait_for(lambda: adjustment_facts(ledger), "The Web did not create the manual debt")
    assert original["principal"] == 5000 and original["adjustments"] == []

    j.native_debts()
    native.click("我欠")
    native.reveal_any("我欠T3Loan", exact=True)
    native.click("我欠T3Loan", stable=True)
    native.click("调整本金", stable=True)
    native.fill("3.00", label="调整金额")
    native.fill("T3Original", label="原因")
    native.click("保存", stable=True)
    wait_for(lambda: len(adjustment_facts(ledger)["adjustments"]) == 1,
        "The production AppContainer and Worker did not deliver the original debt adjustment", 90)

    accepted = adjustment_facts(ledger)
    assert accepted["principal"] == original["principal"] and accepted["version"] == original["version"] + 1
    fact = accepted["adjustments"][0]
    assert (fact["amount"], fact["reason"]) == (300, "T3Original") and fact["key"]
    native.reveal_any("53.00", toward_start=True)
    native.capture("debt-adjustment-accepted-detail")
    native.back()
    native.reveal_any("我欠T3Loan", exact=True)
    native.reveal_any("53.00")
    native.capture("debt-adjustment-accepted-list")
    j.goto(f"/web/debts/{original['public_id']}", receiver=True)
    assert "53.00" in page.inner_text("main") and "T3Original" in page.inner_text("main")
    j.capture("debt-adjustment-accepted-web", receiver=True)
    assert adjustment_facts(ledger) == accepted, "Cross-page reads changed the original accepted command"
    return accepted
