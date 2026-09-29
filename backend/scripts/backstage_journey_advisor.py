"""Real consent, Web/native advisor, audit and no-financial-write consumers."""

import json
from contextlib import closing

from scripts.planning_journey_android import wait_for
from scripts.planning_journey_roles import _member_code


def _audit(ledger_id):
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import Budget, BudgetAdvisorAuditLog

    with SessionLocal() as db:
        rows = db.scalars(select(BudgetAdvisorAuditLog).where(
            BudgetAdvisorAuditLog.tenant_id == ledger_id).order_by(BudgetAdvisorAuditLog.id)).all()
        return {"rows": [{"success": bool(row.success), "error": row.error_code,
                          "suggestions": row.suggestion_count, "input_hash": row.input_hash} for row in rows],
                "budgets": db.scalar(select(func.count()).select_from(Budget).where(Budget.tenant_id == ledger_id))}


def _consent(j, confirmed):
    owner = j.page.context.browser.new_page()
    try:
        owner.goto(j.base_url + "/owner/ai-advisor")
        form = owner.locator('form[action="/owner/ai-advisor/confirmation"]')
        form.locator('[name="confirmed"]').set_checked(confirmed)
        form.get_by_role("button", name="保存确认状态", exact=True).click()
        assert form.locator('[name="confirmed"]').is_checked() == confirmed
        j.capture("ai-owner-consent" if confirmed else "ai-owner-not-consented", page=owner)
    finally:
        owner.close()


def _roles(j):
    base = j.base_url.replace("127.0.0.1", "localhost")
    count = len(j.advisor.inputs)
    for role in ("member", "viewer"):
        with closing(j.page.context.browser.new_context()) as context:
            page = context.new_page()
            page.goto(base + "/web/auth/login?next=/web/budget-advise")
            page.locator('[name="pairing_code"]').fill(_member_code(j.ledger_id, role))
            page.locator('form[action="/web/auth/login"] button[type="submit"]').click()
            page.wait_for_url("**/web/budget-advise*")
            assert page.get_by_role("button", name="获取智能建议", exact=True).count() == 0
            j.capture("ai-" + role + "-read-only-advice", page=page)
    assert len(j.advisor.inputs) == count, "A non-Owner consumer invoked the live provider"


def advisor_consumers(j):
    before = j.facts()
    j.goto("/web/budget-advise")
    assert j.page.get_by_role("button", name="获取智能建议", exact=True).count() == 0
    assert "暂不可用" in j.page.inner_text("main") and not j.advisor.inputs
    _consent(j, True)
    j.goto("/web/budget-advise")
    form = j.page.locator('form[action="/web/budget-advise"]')
    form.get_by_role("button", name="获取智能建议", exact=True).click()
    j.page.get_by_text("合成协议样例：仅供人工核对", exact=True).wait_for()
    assert len(j.advisor.inputs) == 1
    j.capture("ai-web-reference")
    j.advisor.fail_next = True
    form.get_by_role("button", name="获取智能建议", exact=True).click()
    wait_for(lambda: len(_audit(j.ledger_id)["rows"]) == 2, "The failed provider call was not audited")
    assert not _audit(j.ledger_id)["rows"][-1]["success"]
    j.capture("ai-web-outage")
    j.native.plan_home()
    j.native.click("本月储蓄与备用金", stable=True)
    j.native.reveal_any("生成预算建议")
    j.native.click("生成预算建议")
    wait_for(lambda: j.native.has("合成协议样例：仅供人工核对"), "The native consumer did not receive the advisor result", 90)
    j.native.capture("backstage-ai-native-reference")
    _roles(j)
    _consent(j, False)
    j.goto("/web/budget-advise")
    assert j.page.get_by_role("button", name="获取智能建议", exact=True).count() == 0
    audit = _audit(j.ledger_id)
    assert [row["success"] for row in audit["rows"]] == [True, False, True]
    assert audit["budgets"] == 0 and j.facts() == before, "Advice changed budgets or financial facts"
    for inputs in j.advisor.inputs:
        outbound = json.dumps(inputs, ensure_ascii=False)
        assert all(private not in outbound for private in ("星河便利店", "原窗口", "image", "merchant", "note", "pairing"))
    audit["provider_evidence"] = "Synthetic upstream for actual UI/protocol/audit; real local model adapter was separately exercised"
    audit["outbound_calls"] = len(j.advisor.inputs)
    (j.evidence / "advisor-consumer-result.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit
