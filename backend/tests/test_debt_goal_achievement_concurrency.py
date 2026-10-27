"""Real transactions serialize link publication and completed financial commands."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.database import SessionLocal
from app.schemas import (
    DebtGoalLinksReplaceRequest,
    GoalCreateRequest,
    RepaymentCreateRequest,
    RepaymentDraftConfirmRequest,
)
from app.services import (
    debt_command_service,
    goal_debt_repayment_commands,
    goal_debt_repayment_core,
    repayment_capture_correction,
)
from app.services.debt_service import _repayment_draft_confirm
from app.services.goal_debt_repayment_idempotency import replace_debt_repayment_goal_links_idempotently
from app.services.repayment_draft_command_service import confirm_repayment_draft_idempotently
from tests._infra.identity import seeded_owner_account_id
from tests.debt_repayment_goal_helpers import _create_debt_goal, _create_external_debt, _goal_latch_state
from tests.test_debt_goal_command_achievement import _funded_purchase
from tests.test_funds_accounts import _create_funds_account

pytestmark = pytest.mark.real_db


def _repay(debt, actor):
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout = '8s'"))
        return debt_command_service.record_repayment_idempotently(db, tenant_id="owner", actor_account_id=actor,
            public_id=debt["public_id"], idempotency_key=str(uuid4()),
            payload=RepaymentCreateRequest(amount_cents=debt["principal_amount_cents"], expected_row_version=debt["row_version"]))


def test_simultaneous_last_payments_recheck_peers_after_goal_lock(client, identity, monkeypatch):
    debts = [_create_external_debt(client, identity.app_headers) for _ in range(2)]
    goal = _create_debt_goal(client, identity.app_headers, name="两笔同时结清",
        debt_public_ids=[debt["public_id"] for debt in debts]).json()
    actor = seeded_owner_account_id()
    ready = Barrier(2)
    stage = debt_command_service.stage_debt_goal_achievements

    def both_payments_staged(db, **kwargs):
        ready.wait(timeout=10)
        stage(db, **kwargs)

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(debt_command_service, "stage_debt_goal_achievements", both_payments_staged)
        futures = [pool.submit(_repay, debt, actor) for debt in debts]
        for future in futures:
            assert future.result(timeout=20).status == "cleared"
    assert _goal_latch_state(goal["public_id"])[1] == 1


def test_goal_creation_waits_for_last_repayment_before_publishing_links(client, identity, monkeypatch):
    debt = _create_external_debt(client, identity.app_headers)
    actor = seeded_owner_account_id()
    payment_ready, publish_ready, release_payment = Event(), Event(), Event()
    stage = debt_command_service.stage_debt_goal_achievements
    resolve = goal_debt_repayment_core._resolve_linked_debts

    def paused_stage(db, **kwargs):
        payment_ready.set()
        assert release_payment.wait(timeout=10)
        stage(db, **kwargs)

    def observed_resolve(*args, **kwargs):
        publish_ready.set()
        return resolve(*args, **kwargs)

    def create():
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            return goal_debt_repayment_core.create_debt_repayment_goal_idempotently(db, tenant_id="owner",
                payload=GoalCreateRequest(name="还款中创建", goal_type="debt_repayment", debt_public_ids=[debt["public_id"]]),
                idempotency_key=str(uuid4()))

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(debt_command_service, "stage_debt_goal_achievements", paused_stage)
        patch.setattr(goal_debt_repayment_core, "_resolve_linked_debts", observed_resolve)
        payment = pool.submit(_repay, debt, actor)
        try:
            assert payment_ready.wait(timeout=10)
            creating = pool.submit(create)
            assert publish_ready.wait(timeout=10)
            with pytest.raises(TimeoutError):
                creating.result(timeout=0.5)
        finally:
            release_payment.set()
        assert payment.result(timeout=15).status == "cleared"
        created = creating.result(timeout=15)
    assert _goal_latch_state(created.public_id)[1] == 1


@pytest.mark.parametrize("replace", [False, True])
def test_goal_publication_follows_capture_account_then_debt_order(client, identity, monkeypatch, replace):
    # Y is older than X: capture holds source Account X -> Debt X before repaying
    # manual Debt Y. A goal must not take Debt Y and then wait for Debt X.
    manual = _create_external_debt(client, identity.app_headers)
    credit = _create_funds_account(client, identity, "来源信用账户X", "credit", 0, visibility="ledger")
    purchase = _funded_purchase(client, identity, credit)
    captured = client.post(f"/api/expenses/{purchase['id']}/repayment-draft", headers=identity.app_headers,
        json={"expected_row_version": purchase["row_version"]})
    assert captured.status_code == 201, captured.text
    draft = captured.json()
    old = (_create_debt_goal(client, identity.app_headers, name="原目标", debt_public_ids=[manual["public_id"]]).json()
        if replace else None)
    actor = seeded_owner_account_id()
    source_reversed, publish_ready, release_capture = Event(), Event(), Event()
    reverse_source = _repayment_draft_confirm._reverse_source_expense
    resolve = goal_debt_repayment_core._resolve_linked_debts

    def paused_reverse(*args, **kwargs):
        result = reverse_source(*args, **kwargs)
        source_reversed.set()
        assert release_capture.wait(timeout=10)
        return result

    def observed_resolve(*args, **kwargs):
        publish_ready.set()
        return resolve(*args, **kwargs)

    def confirm():
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            return confirm_repayment_draft_idempotently(db, tenant_id="owner", actor_account_id=actor,
                public_id=draft["public_id"], idempotency_key=str(uuid4()), payload=RepaymentDraftConfirmRequest(
                    target_debt_public_id=manual["public_id"], expected_row_version=manual["row_version"]))

    def publish():
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            linked = [manual["public_id"], credit["debt_public_id"]]
            if old is not None:
                return replace_debt_repayment_goal_links_idempotently(db, tenant_id="owner", public_id=old["public_id"],
                    idempotency_key=str(uuid4()), payload=DebtGoalLinksReplaceRequest(
                        expected_row_version=old["row_version"], debt_public_ids=linked))
            return goal_debt_repayment_core.create_debt_repayment_goal_idempotently(db, tenant_id="owner",
                idempotency_key=str(uuid4()), payload=GoalCreateRequest(
                    name="还款中关联", goal_type="debt_repayment", debt_public_ids=linked))

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(_repayment_draft_confirm, "_reverse_source_expense", paused_reverse)
        patch.setattr(goal_debt_repayment_core, "_resolve_linked_debts", observed_resolve)
        patch.setattr(goal_debt_repayment_commands, "_resolve_linked_debts", observed_resolve)
        confirming = pool.submit(confirm)
        try:
            assert source_reversed.wait(timeout=10)
            publishing = pool.submit(publish)
            assert publish_ready.wait(timeout=10)
            with pytest.raises(TimeoutError):
                publishing.result(timeout=0.5)
        finally:
            release_capture.set()
        assert confirming.result(timeout=15).status == "confirmed"
        goal = publishing.result(timeout=15)
    assert _goal_latch_state(goal.public_id)[1] == (2 if replace else 1)


@pytest.mark.parametrize("replace", [False, True])
def test_goal_publication_serializes_with_funded_capture_restoration(client, identity, monkeypatch, replace):
    # Restoring the confirmed manual repayment needs both source credit X and
    # manual Debt Y. It must not hold Y while a goal holds X and waits for Y.
    manual = _create_external_debt(client, identity.app_headers)
    credit = _create_funds_account(client, identity, "待恢复信用账户X", "credit", 0, visibility="ledger")
    purchase = _funded_purchase(client, identity, credit)
    captured = client.post(f"/api/expenses/{purchase['id']}/repayment-draft", headers=identity.app_headers,
        json={"expected_row_version": purchase["row_version"]})
    assert captured.status_code == 201, captured.text
    draft = captured.json()
    old = (_create_debt_goal(client, identity.app_headers, name="恢复前目标", debt_public_ids=[manual["public_id"]]).json()
        if replace else None)
    draft_url = f"/api/repayment-drafts/{draft['public_id']}"
    confirmed = client.post(draft_url + "/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"target_debt_public_id": manual["public_id"], "expected_row_version": manual["row_version"]})
    assert confirmed.status_code == 201, confirmed.text
    versions = client.get(draft_url, headers=identity.app_headers).json()["correction_versions"]
    correction = {"reason": "核对为原信用消费", "correction_versions": versions}
    correction_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    debt_locked, publish_ready, release_restore = Event(), Event(), Event()
    correction_debt = repayment_capture_correction.correction_debt
    resolve = goal_debt_repayment_core._resolve_linked_debts

    def paused_debt(db, draft, *, lock=False):
        if lock:
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
        result = correction_debt(db, draft, lock=lock)
        if lock:
            debt_locked.set()
            assert release_restore.wait(timeout=10)
        return result

    def observed_resolve(*args, **kwargs):
        publish_ready.set()
        return resolve(*args, **kwargs)

    def publish():
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            linked = [manual["public_id"], credit["debt_public_id"]]
            if old is not None:
                return replace_debt_repayment_goal_links_idempotently(db, tenant_id="owner", public_id=old["public_id"],
                    idempotency_key=str(uuid4()), payload=DebtGoalLinksReplaceRequest(
                        expected_row_version=old["row_version"], debt_public_ids=linked))
            return goal_debt_repayment_core.create_debt_repayment_goal_idempotently(db, tenant_id="owner",
                idempotency_key=str(uuid4()), payload=GoalCreateRequest(
                    name="恢复中关联", goal_type="debt_repayment", debt_public_ids=linked))

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(repayment_capture_correction, "correction_debt", paused_debt)
        patch.setattr(goal_debt_repayment_core, "_resolve_linked_debts", observed_resolve)
        patch.setattr(goal_debt_repayment_commands, "_resolve_linked_debts", observed_resolve)
        restoring = pool.submit(client.post, draft_url + "/as-expense", headers=correction_headers, json=correction)
        try:
            assert debt_locked.wait(timeout=10)
            publishing = pool.submit(publish)
            assert publish_ready.wait(timeout=10)
            with pytest.raises(TimeoutError):
                publishing.result(timeout=0.5)
        finally:
            release_restore.set()
        restored = restoring.result(timeout=15)
        assert restored.status_code == 200, restored.text
        goal = publishing.result(timeout=15)
    assert restored.json()["expense_id"] == purchase["id"]
    assert goal.debt_repayment.evaluation_state == "in_progress"
    assert _goal_latch_state(goal.public_id)[1] != goal.debt_repayment.goal_version
    assert client.get(f"/api/funds/accounts/{credit['public_id']}", headers=identity.app_headers).json()["balance_minor"] == -10000
    assert client.get(f"/api/debts/{manual['public_id']}", headers=identity.app_headers).json()["remaining_amount_cents"] == 10000
    assert client.post(draft_url + "/as-expense", headers=correction_headers, json=correction).json() == restored.json()
