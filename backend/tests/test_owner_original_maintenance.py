"""Actual local Owner commands, persisted tasks and files in the PostgreSQL lane."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Account, BackgroundTask, Ledger, LedgerMember
from app.routes.owner_console import _require_local
from app.services import background_task_executor, background_task_service
from app.services.orphan_maintenance_tasks import remaining_candidates, task_result
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests.test_orphan_original_continuity import _old_file

pytestmark = pytest.mark.real_db


@pytest.fixture
def local_client(client, monkeypatch):
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")
    app.dependency_overrides[_require_local] = lambda: None
    try:
        yield client
    finally:
        app.dependency_overrides.pop(_require_local, None)


def _post(client, path, **data):
    response = client.post(path, data={"ledger_id": "owner", **data}, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    return location, parse_qs(urlparse(location).query)["task_id"][0]


def _task(public_id):
    with SessionLocal() as db:
        return db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == public_id))


def test_owner_inspects_previews_and_continues_only_frozen_unfinished_files(local_client, identity, monkeypatch):
    files = [_old_file(f"owner-inspect-{index}.png") for index in range(13)]
    client_ref = str(uuid4())
    location, inspection_id = _post(local_client, "/owner/originals/inspect", client_ref=client_ref)
    inspection = _task(inspection_id)
    assert inspection.status == "completed" and task_result(inspection)["candidate_files"] == 13
    assert all(path.is_file() for path in files)
    assert _post(local_client, "/owner/originals/inspect", client_ref=client_ref) == (location, inspection_id)
    page = local_client.get(location)
    assert page.status_code == 200 and "下一页文件" in page.text and "csrf_token" in page.text
    assert "owner-inspect-" not in page.text
    preview = f"/owner/originals/tasks/{inspection_id}/files/0?ledger_id=owner"
    assert local_client.get(preview).content == PNG_BYTES
    assert local_client.get(preview.replace("ledger_id=owner", "ledger_id=tester_1")).status_code == 404
    api = local_client.get(f"/api/tasks/{inspection_id}", headers=identity.app_headers)
    assert api.status_code == 200 and "_candidates" not in api.text and "owner-inspect-" not in api.text
    assert local_client.get(location + "&files_page=2").text.count('class="original-candidate"') == 1
    action = f"/owner/originals/tasks/{inspection_id}/dispose"
    assert local_client.post(action, data={"ledger_id": "owner"}, follow_redirects=False).status_code == 422
    late = _old_file("not-in-owner-inspection.png")
    real_unlink = Path.unlink

    def locked_file(path, *args, **kwargs):
        if path == files[0]:
            raise PermissionError("isolated file busy")
        return real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", locked_file)
        partial_location, disposal_id = _post(local_client, action, confirmed="true")
    result = task_result(_task(disposal_id))
    assert (result["deleted_files"], result["failed_files"], result["candidate_files"]) == (12, 1, 13)
    assert files[0].is_file() and late.is_file()
    assert "仍有文件待处理" in local_client.get(partial_location).text
    original_inspection = local_client.get(location).text
    assert "查看本次处置结果" in original_inspection and "删除本次候选文件" not in original_inspection
    assert _post(local_client, action, confirmed="true") == (partial_location, disposal_id)
    continued_location, child_id = _post(local_client, f"/owner/originals/tasks/{disposal_id}/continue")
    child = _task(child_id)
    assert child.status == "completed" and task_result(child)["deleted_files"] == 1
    assert task_result(child)["candidate_files"] == 1 and not remaining_candidates(child)
    assert not any(path.exists() for path in files) and late.is_file()
    assert _post(local_client, f"/owner/originals/tasks/{disposal_id}/continue") == (continued_location, child_id)
    assert "查看原检查范围" in local_client.get(continued_location).text
    assert task_result(_task(disposal_id)) == result, "Continuation must not rewrite the previous outcome"


def test_restart_preserves_cancelled_disposal_input_and_requires_explicit_continuation(local_client, monkeypatch):
    original = _old_file("restart-candidate.png")
    _, inspection_id = _post(local_client, "/owner/originals/inspect", client_ref=str(uuid4()))
    with monkeypatch.context() as patch:
        patch.setattr(background_task_executor, "submit_task", lambda *args, **kwargs: None)
        _, public_id = _post(local_client, f"/owner/originals/tasks/{inspection_id}/dispose", confirmed="true")
    saved_input = _task(public_id).input_payload_json
    _post(local_client, f"/owner/originals/tasks/{public_id}/cancel")
    assert _task(public_id).cancellation_requested_at is not None
    background_task_service.recover_orphaned_tasks()
    interrupted = _task(public_id)
    assert interrupted.status == "failed" and interrupted.error_code == "orphaned_after_restart"
    assert interrupted.input_payload_json == saved_input and original.is_file()
    late = _old_file("restart-late.png")
    _, child_id = _post(local_client, f"/owner/originals/tasks/{public_id}/continue")
    assert _task(child_id).status == "completed" and not original.exists() and late.is_file()
    assert json.loads(_task(child_id).input_payload_json)["inspection_id"] == inspection_id


@pytest.mark.parametrize("denial", ["member", "disabled_membership", "disabled_account", "foreign_owner"])
def test_original_maintenance_rechecks_local_ownership(local_client, denial):
    candidate = _old_file("unauthorized-candidate.png")
    with SessionLocal() as db:
        owner = db.scalar(select(Account).order_by(Account.id))
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner", LedgerMember.account_id == owner.id))
        if denial == "member":
            member.role = "member"
        elif denial == "disabled_membership":
            member.disabled_at = now_utc()
        elif denial == "disabled_account":
            owner.disabled_at = now_utc()
        else:
            foreign = Account(display_name="Other local principal")
            db.add(foreign)
            db.flush()
            ledger.owner_account_id = foreign.id
        db.commit()
    response = local_client.post("/owner/originals/inspect", data={"ledger_id": "owner", "client_ref": str(uuid4())})
    assert response.status_code == 403 and candidate.is_file()
    assert local_client.get("/owner/originals?ledger_id=owner").status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(BackgroundTask.id).where(BackgroundTask.task_type == "orphan_inspection")) is None


def test_archived_ledger_storage_remains_accessible_without_restoring_financial_writes(local_client):
    candidate = _old_file("archived-candidate.png", tenant_id="tester_1")
    with SessionLocal() as db:
        db.scalar(select(Ledger).where(Ledger.ledger_id == "tester_1")).archived_at = now_utc()
        db.commit()
    page = local_client.get("/owner/originals?ledger_id=tester_1")
    assert page.status_code == 200 and "（已归档）" in page.text
    _, public_id = _post(local_client, "/owner/originals/inspect", ledger_id="tester_1", client_ref=str(uuid4()))
    assert task_result(_task(public_id))["candidate_files"] == 1 and candidate.is_file()
    with SessionLocal() as db:
        assert db.scalar(select(Ledger).where(Ledger.ledger_id == "tester_1")).archived_at is not None


def test_original_maintenance_is_not_a_remote_admin_surface(client, identity):
    assert client.get("/owner/originals", headers=identity.admin_headers).status_code == 403
    response = client.post("/owner/originals/inspect", headers=identity.admin_headers,
        data={"ledger_id": "owner", "client_ref": str(uuid4())})
    assert response.status_code == 403
