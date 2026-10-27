"""Rule batches and explicit corrections must serialize overlapping Expense rows."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, RuleApplicationBatch, RuleApplicationChange
from app.services import expense_correction_service
from app.services.currency_binding_service import resolve_write_capability
from app.services.rule_application_service import _apply, _history
from tests.test_rule_application_commands import _expense, _preview


def _rule_intent(client, identity, action):
    ids = [_expense("confirmed") for _ in range(2)]
    with SessionLocal() as db:
        resolve_write_capability(db)
        for identifier in ids:
            # Supported historical facts may have no known publication time
            # and therefore no migration-generated initial revision.
            db.get(Expense, identifier).confirmed_at = None
        db.commit()
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    created = client.post("/api/rules/categories", headers=headers,
        json={"keyword": "OriginalApplication", "category": "餐饮"})
    assert created.status_code == 200, created.text
    path = "/api/rules/apply-confirmed"
    body = {**_preview(client, identity.app_headers, "confirmed"), "reason": "批量规则核对"}
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    if action == "rollback":
        accepted = client.post(path, headers=headers, json=body)
        assert accepted.status_code == 200, accepted.text
        batch_id = accepted.json()["application_public_id"]
        with SessionLocal() as db:
            batch = db.scalar(select(RuleApplicationBatch).where(RuleApplicationBatch.public_id == batch_id))
            # Retained audit order stays in the original newest-first preview order.
            assert list(db.scalars(select(RuleApplicationChange.expense_id)
                .where(RuleApplicationChange.batch_id == batch.id).order_by(RuleApplicationChange.id))) == ids[::-1]
        path = f"/api/rules/applications/{batch_id}/rollback"
        body = {"reason": "撤回这批规则分类"}
    versions = {identifier: client.get(f"/api/expenses/{identifier}", headers=identity.app_headers).json()["row_version"]
        for identifier in ids}
    return ids, versions, path, headers, body


def _coordinate_first_rows(monkeypatch, action):
    rule_locked, correction_attempted, correction_locked, rule_continue = (Event() for _ in range(4))
    module, name = (_apply, "_try_apply_rule_category") if action == "apply" else (_history, "_try_rollback_rule_change")
    original_rule = getattr(module, name)
    original_correction = expense_correction_service._apply_one_batch_correction
    rule_calls = 0
    correction_calls = 0

    def rule_row(*args, **kwargs):
        nonlocal rule_calls
        result = original_rule(*args, **kwargs)
        rule_calls += 1
        if rule_calls == 1:
            rule_locked.set()
            assert correction_attempted.wait(10)
            # With consistent lock order, the correction waits on this row.
            # Opposite orders let both first writes finish and then deadlock.
            correction_locked.wait(1)
            rule_continue.set()
        return result

    def correction_row(*args, **kwargs):
        nonlocal correction_calls
        correction_calls += 1
        if correction_calls == 1:
            correction_attempted.set()
        result = original_correction(*args, **kwargs)
        if correction_calls == 1:
            correction_locked.set()
            assert rule_continue.wait(10)
        return result

    monkeypatch.setattr(module, name, rule_row)
    monkeypatch.setattr(expense_correction_service, "_apply_one_batch_correction", correction_row)
    return rule_locked


@pytest.mark.real_db
@pytest.mark.parametrize("action", ["apply", "rollback"])
def test_overlapping_rule_and_correction_batches_return_occ_not_database_deadlock(client, identity, monkeypatch, action):
    ids, versions, path, headers, body = _rule_intent(client, identity, action)
    rule_locked = _coordinate_first_rows(monkeypatch, action)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rule_request = pool.submit(client.post, path, headers=headers, json=body)
        assert rule_locked.wait(10)
        correction = pool.submit(client.post, "/api/expenses/confirmed/batch-update",
            headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"expense_ids": ids, "expected_row_version_by_id": versions,
                "category": "购物", "reason": "独立的明确更正"})
        rule_result, correction_result = rule_request.result(timeout=20), correction.result(timeout=20)
    assert rule_result.status_code == 200, rule_result.text
    assert correction_result.status_code == 409, correction_result.text
    assert correction_result.json()["error"] == "state_conflict"
    expected_category = "餐饮" if action == "apply" else "其他"
    for identifier in ids:
        latest = client.get(f"/api/expenses/{identifier}", headers=identity.app_headers)
        assert latest.status_code == 200 and latest.json()["category"] == expected_category
        assert latest.json()["row_version"] == versions[identifier] + 1
        assert latest.json()["confirmed_at"] is None
    assert client.post(path, headers=headers, json=body).json() == rule_result.json()
