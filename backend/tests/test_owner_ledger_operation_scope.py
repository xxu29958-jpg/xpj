"""Owner operations follow the selected ledger without falling back after access loss."""

import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Account, AlgorithmDecision, Expense, Ledger, LedgerMember
from app.models.ai_advisor import BudgetAdvisorAuditLog
from app.routes.owner_console import _require_local
from app.services.learning_service import DecisionDraft, record_decision
from app.services.time_service import now_utc


@pytest.fixture
def owner(client):
    app.dependency_overrides[_require_local] = lambda: None
    try:
        yield client
    finally:
        app.dependency_overrides.pop(_require_local, None)


def _seed_records(db, ledger_id, marker):
    expense = Expense(tenant_id=ledger_id, amount_cents=1234, merchant=marker, category="其他",
                      source="pytest", raw_text="", status="pending", expense_time=now_utc())
    db.add(expense)
    db.flush()
    active = record_decision(db, DecisionDraft(tenant_id=ledger_id, decision_type="category_suggestion",
        algorithm_version="scope-shared-v1", subject_kind="expense", subject_id=expense.id, payload={"category": "餐饮"}))
    expired = record_decision(db, DecisionDraft(tenant_id=ledger_id, decision_type="category_suggestion",
        algorithm_version=f"expired-{marker}", subject_kind="expense", subject_id=expense.id, payload={"category": "其他"}),
        now=now_utc() - timedelta(days=200))
    expired.status = "dismissed"
    expired.retention_days = 1
    db.add(BudgetAdvisorAuditLog(tenant_id=ledger_id, provider="empty", model=marker, input_hash=marker, success=1,
        month="2026-01" if ledger_id == "owner" else "2026-02"))
    db.flush()
    return active.id, active.public_id, expired.id, expense.id


@pytest.fixture
def ledgers(owner, identity):
    created = owner.post("/api/ledgers", headers=identity.admin_headers, json={"name": "旅行"})
    assert created.status_code == 201, created.text
    target = created.json()["ledger_id"]
    with SessionLocal() as db:
        source_rows = _seed_records(db, "owner", "home-record")
        target_rows = _seed_records(db, target, "travel-record")
        db.commit()
    return target, source_rows, target_rows


def test_selected_ledger_records_are_visible_on_all_three_pages(owner, ledgers):
    target, source_rows, target_rows = ledgers
    for page, visible, absent in (
        ("learning-maintenance", target_rows[1], source_rows[1]),
        ("algorithm-versions", "expired-travel-record", "expired-home-record"),
        ("ai-advisor", "2026-02", "2026-01"),
    ):
        result = owner.get(f"/owner/{page}", params={"ledger_id": target})
        assert result.status_code == 200, result.text
        assert f'value="{target}" selected' in result.text
        assert visible in result.text and absent not in result.text


@pytest.mark.parametrize("action", ["withdraw", "dismiss", "cleanup"])
def test_operation_changes_selected_ledger_and_keeps_financial_facts(owner, ledgers, action):
    target, source_rows, target_rows = ledgers
    page = "algorithm-versions" if action == "withdraw" else "learning-maintenance"
    endpoint = {"withdraw": "withdraw", "dismiss": "dismiss-decision", "cleanup": "run"}[action]
    data = {"ledger_id": target, "decision_type": "category_suggestion", "algorithm_version": "scope-shared-v1",
            "decision_public_id": target_rows[1]}
    result = owner.post(f"/owner/{page}/{endpoint}", data=data, follow_redirects=False)
    assert result.status_code == 303, result.text
    section = {"withdraw": "algorithm-history", "dismiss": "learning-candidates", "cleanup": "learning-volume"}[action]
    assert result.headers["location"] == f"/owner/{page}?ledger_id={target}#{section}"
    with SessionLocal() as db:
        assert db.get(AlgorithmDecision, source_rows[0]).status == "active"
        assert db.get(AlgorithmDecision, source_rows[2]) is not None
        if action == "cleanup":
            assert db.get(AlgorithmDecision, target_rows[2]) is None
            assert db.get(AlgorithmDecision, target_rows[0]).status == "active"
        else:
            expected = "withdrawn" if action == "withdraw" else "dismissed"
            assert db.get(AlgorithmDecision, target_rows[0]).status == expected
        for row_set in (source_rows, target_rows):
            expense = db.get(Expense, row_set[3])
            assert (expense.amount_cents, expense.category, expense.status) == (1234, "其他", "pending")


def test_other_ledger_decision_cannot_be_dismissed_through_selected_ledger(owner, ledgers):
    target, source_rows, _ = ledgers
    result = owner.post("/owner/learning-maintenance/dismiss-decision",
        data={"ledger_id": target, "decision_public_id": source_rows[1]}, follow_redirects=False)
    assert result.status_code == 303
    with SessionLocal() as db:
        assert db.get(AlgorithmDecision, source_rows[0]).status == "active"


@pytest.mark.parametrize("reason", ["foreign", "archived", "lost_owner", "disabled_account"])
def test_stale_or_forged_scope_is_denied_before_read_and_mutation(owner, ledgers, reason):
    target, source_rows, target_rows = ledgers
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == target))
        if reason == "foreign":
            outsider = Account(display_name="其他家庭")
            db.add(outsider)
            db.flush()
            ledger.owner_account_id = outsider.id
        elif reason == "archived":
            ledger.archived_at = now_utc()
        elif reason == "disabled_account":
            db.get(Account, ledger.owner_account_id).disabled_at = now_utc()
        else:
            db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == target,
                LedgerMember.account_id == ledger.owner_account_id)).role = "member"
        db.commit()
    for page in ("learning-maintenance", "algorithm-versions", "ai-advisor"):
        assert owner.get(f"/owner/{page}", params={"ledger_id": target}).status_code == 403
    for endpoint in ("learning-maintenance/run", "learning-maintenance/dismiss-decision", "algorithm-versions/withdraw"):
        result = owner.post(f"/owner/{endpoint}", data={"ledger_id": target, "decision_public_id": target_rows[1],
            "decision_type": "category_suggestion", "algorithm_version": "scope-shared-v1"})
        assert result.status_code == 403, result.text
    assert owner.post(f"/owner/ai-advisor/test?ledger_id={target}").status_code == 403
    with SessionLocal() as db:
        for rows in (source_rows, target_rows):
            assert db.get(AlgorithmDecision, rows[0]).status == "active"
            assert db.get(AlgorithmDecision, rows[2]) is not None


def test_no_manageable_ledger_has_no_default_data_fallback(owner, ledgers):
    with SessionLocal() as db:
        for account in db.scalars(select(Account)):
            account.disabled_at = now_utc()
        db.commit()
    for page in ("learning-maintenance", "algorithm-versions", "ai-advisor"):
        result = owner.get(f"/owner/{page}")
        assert result.status_code == 200, result.text
        assert "当前没有可管理的账本" in result.text
        assert "home-record" not in result.text and "travel-record" not in result.text
        assert "2026-01" not in result.text and "2026-02" not in result.text
        assert 'action="/owner/learning-maintenance/run"' not in result.text
        assert 'action="/owner/algorithm-versions/withdraw"' not in result.text
    assert owner.post("/owner/learning-maintenance/run").status_code == 403


def test_invalid_model_form_keeps_ledger_and_unsaved_input(owner, ledgers):
    target, _, _ = ledgers
    result = owner.post(f"/owner/ai-advisor/settings?ledger_id={target}", data={"timeout_seconds": "0", "model": "draft-model"})
    assert result.status_code == 422, result.text
    assert f'value="{target}" selected' in result.text
    assert f'action="/owner/ai-advisor/settings?ledger_id={target}"' in result.text
    assert 'value="draft-model"' in result.text
    selection = re.search(r'<form method="get" action="([^"]+)"', result.text)
    assert selection is not None
    switched = owner.get(selection.group(1).split("#", 1)[0], params={"ledger_id": "owner"})
    assert switched.status_code == 200, switched.text
    assert 'value="owner" selected' in switched.text
    assert "2026-01" in switched.text and "2026-02" not in switched.text
