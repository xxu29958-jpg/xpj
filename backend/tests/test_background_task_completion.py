"""Task terminal publication owns the atomic admission/after-commit dispatch order."""

from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.models import BackgroundTask
from app.services import background_task_service, background_task_worker, pending_enrichment_task_service
from app.services.background_task_handler_api import TaskCancelledError
from app.services.background_task_registry import TaskHandlerRegistry


class CompletionRegistry(TaskHandlerRegistry):
    """Use the proposed seam without requiring a missing constructor/import to fail."""

    def __init__(self, handler, completion):
        super().__init__({"expense_enrichment": handler})
        self.completion = completion

    def prepare_completion(self, db, task):
        return self.completion(db, task)


@pytest.fixture
def worker(monkeypatch):
    db = Mock(spec=Session)
    parent = BackgroundTask(id=1, task_type="expense_enrichment", status="running", tenant_id="owner")
    child = BackgroundTask(id=2, task_type="expense_fx", status="queued", tenant_id="owner")
    db.get.return_value = parent
    monkeypatch.setattr(background_task_worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(background_task_worker, "claim_queued_task", lambda *_: parent)
    return db, parent, child


@pytest.mark.parametrize("durable_result", [False, True])
def test_completion_flushes_parent_then_admits_then_commits_then_dispatches(worker, monkeypatch, durable_result):
    db, parent, child = worker
    order = []
    payload = {"expense_id": 7, "tenant_id": "owner", "expected_row_version": 1}
    result = '{"expense_id":7,"outcome":"updated","row_version":2}'
    if durable_result:
        parent.result_summary_json = result
    monkeypatch.setattr(pending_enrichment_task_service, "enrich_pending_expense", Mock(side_effect=AssertionError("No OCR replay")))

    def handler(session, task, original):
        order.append("handler")
        if durable_result:
            pending_enrichment_task_service.run_pending_expense_enrichment_task(session, task, original)
        else:
            task.result_summary_json = result

    def flush():
        assert parent.status == "completed" and parent.result_summary_json == result
        order.append("flush-completed")

    def completion(session, task):
        assert session is db and task is parent and order[-1] == "flush-completed"
        order.append("admit-child")
        return background_task_service.PreparedBackgroundTask(child, 2, "child-receipt", {}, registry)

    def submit(session, prepared, *, runner):
        assert session is db and prepared.task is child and order[-1] == "commit"
        assert runner is background_task_worker.run_task
        assert parent.status == "completed"
        order.append("submit-child")

    registry = CompletionRegistry(handler, completion)
    db.flush.side_effect = flush
    db.commit.side_effect = lambda: order.append("commit")
    monkeypatch.setattr("app.services.background_task_executor.submit_committed", submit)
    background_task_worker.run_task(1, payload, registry)
    assert order == ["handler", "flush-completed", "admit-child", "commit", "submit-child"]
    assert parent.result_summary_json == result


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled", "cancellation"])
def test_terminal_or_cancelled_handler_never_prepares_a_child(worker, terminal):
    db, parent, _child = worker
    completion = Mock(side_effect=AssertionError("A terminal task cannot admit a child"))

    def handler(_db, task, _payload):
        if terminal == "cancellation":
            raise TaskCancelledError
        task.status = terminal

    registry = CompletionRegistry(handler, completion)
    background_task_worker.run_task(1, {}, registry)
    completion.assert_not_called()
    assert parent.status == ("cancelled" if terminal == "cancellation" else terminal)
    db.flush.assert_not_called()


def test_child_submission_refusal_preserves_completed_parent(worker, monkeypatch):
    db, parent, child = worker
    registry = CompletionRegistry(lambda *_: None, lambda *_: background_task_service.PreparedBackgroundTask(
        child, 2, "child-receipt", {}, registry))

    def refuse(_db, _prepared, *, runner):
        assert parent.status == "completed" and db.commit.called
        assert runner is background_task_worker.run_task
        child.status = "failed"
        raise background_task_service.BackgroundTaskSubmissionError("child-receipt")

    monkeypatch.setattr("app.services.background_task_executor.submit_committed", refuse)
    background_task_worker.run_task(1, {}, registry)
    assert parent.status == "completed" and child.status == "failed"
