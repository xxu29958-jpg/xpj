"""Accepted spending definitions remain reviewable, independently of live progress."""

import json
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, Goal, GoalRevision, LedgerMember
from app.services import goal_service
from app.services.currency_binding_service import resolve_write_capability
from tests import test_web_goal_edit_continuity
from tests._runtime_protocol import negotiated_headers

pytestmark = pytest.mark.real_db
web_client = test_web_goal_edit_continuity.web_client

DEFINITION_FIELDS = (
    "name", "goal_type", "period", "month", "category", "target_amount_cents", "home_currency_code", "status",
)


def _headers(client, identity, key=None):
    return {**negotiated_headers(client, identity.app_headers), "Idempotency-Key": key or str(uuid4())}


def _create(client, identity):
    body = {"name": "原交通上限", "month": "2026-05", "category": "交通",
        "target_amount_cents": 1200, "home_currency_code": "JPY"}
    key = str(uuid4())
    response = client.post("/api/goals", json=body, headers=_headers(client, identity, key))
    assert response.status_code == 201, response.text
    return body, key, response.json()


def _edit(client, identity, previous, **changes):
    body = {"expected_row_version": previous["row_version"], "home_currency_code": "JPY", **changes}
    key = str(uuid4())
    response = client.patch(f'/api/goals/{previous["public_id"]}', json=body,
        headers=_headers(client, identity, key))
    assert response.status_code == 200, response.text
    assert response.json()["row_version"] == previous["row_version"] + 1
    return body, key, response.json()


def _accepted_lifecycle(client, identity):
    create_body, create_key, original = _create(client, identity)
    edit_body, edit_key, edited = _edit(client, identity, original,
        name="六月餐饮上限", month="2026-06", category="餐饮", target_amount_cents=1800)
    _, _, later = _edit(client, identity, edited, name="后来调整", target_amount_cents=2200)
    url = f'/api/goals/{original["public_id"]}'
    replay = client.patch(url, json=edit_body, headers=_headers(client, identity, edit_key))
    assert replay.status_code == 200 and replay.json() == edited
    replay_create = client.post("/api/goals", json=create_body, headers=_headers(client, identity, create_key))
    assert replay_create.status_code == 201 and replay_create.json() == original
    stale = client.patch(url, json=edit_body, headers=_headers(client, identity))
    assert stale.status_code == 409, stale.text
    archived = client.post(f"{url}/archive", headers=identity.app_headers)
    assert archived.status_code == 200, archived.text
    archived = archived.json()
    assert archived["status"] == "archived" and archived["row_version"] == later["row_version"] + 1
    repeat_archive = client.post(f"{url}/archive", headers=identity.app_headers)
    assert repeat_archive.status_code == 200 and repeat_archive.json()["row_version"] == archived["row_version"]
    restored = client.post(f"{url}/restore", headers=identity.app_headers,
        json={"expected_row_version": archived["row_version"]})
    assert restored.status_code == 200, restored.text
    restored = restored.json()
    assert restored["status"] == "active" and restored["row_version"] == archived["row_version"] + 1
    repeat_restore = client.post(f"{url}/restore", headers=identity.app_headers,
        json={"expected_row_version": archived["row_version"]})
    assert repeat_restore.status_code == 200 and repeat_restore.json()["row_version"] == restored["row_version"]
    current = client.get(url, headers=identity.app_headers)
    assert current.status_code == 200 and current.json()["row_version"] == restored["row_version"]
    return [original, edited, later, archived, restored]


def _history(client, identity, public_id, **params):
    response = client.get(f"/api/goals/{public_id}/history", headers=identity.app_headers, params=params)
    assert response.status_code == 200, response.text
    history = response.json()
    assert history["ledger_id"] == "owner" and history["public_id"] == public_id
    return history


def _assert_definition(item, receipt, kind):
    assert item["row_version"] == receipt["row_version"]
    assert item["change_kind"] == kind
    assert datetime.fromisoformat(item["recorded_at"].replace("Z", "+00:00")).tzinfo is not None
    assert item["snapshot"] == {field: receipt[field] for field in DEFINITION_FIELDS}


def test_replayed_commands_and_recycle_round_trip_keep_original_definitions_and_stable_pages(client, identity):
    accepted = _accepted_lifecycle(client, identity)
    public_id = accepted[0]["public_id"]
    first = _history(client, identity, public_id, limit=2)
    assert len(first["items"]) == 2
    # A later accepted edit must not move an already-issued before_version window.
    _, _, newest = _edit(client, identity, accepted[-1], name="分页后修改", target_amount_cents=2500)
    second = _history(client, identity, public_id, limit=2, before_version=first["next_before_version"])
    third = _history(client, identity, public_id, limit=2, before_version=second["next_before_version"])
    assert third["next_before_version"] is None
    items = first["items"] + second["items"] + third["items"]
    assert len(items) == 5
    for item, receipt, kind in zip(items, reversed(accepted), ["restore", "archive", "edit", "edit", "create"], strict=True):
        _assert_definition(item, receipt, kind)
    repeated = _history(client, identity, public_id, limit=2, before_version=first["next_before_version"])
    assert repeated == second  # Includes the originally recorded times, not the read time.
    latest = _history(client, identity, public_id)
    assert len(latest["items"]) == 6
    _assert_definition(latest["items"][0], newest, "edit")
    invalid = client.get(f"/api/goals/{public_id}/history", headers=identity.app_headers,
        params={"before_version": 0})
    assert invalid.status_code == 422


def test_portable_outlet_keeps_all_original_definitions_without_screen_filters_or_other_ledgers(client, identity):
    accepted = _accepted_lifecycle(client, identity)
    response = client.get("/api/exports/portable", headers=identity.app_headers, params={"month": "1999-01"})
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as package:
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["ledger_id"] == "owner" and manifest["records_complete"] is True
        goals = [json.loads(line) for line in package.read("records/goals.jsonl").splitlines()]
        goal = next(row for row in goals if row["public_id"] == accepted[0]["public_id"])
        assert goal["row_version"] == accepted[-1]["row_version"]
        assert "records/goal_revisions.jsonl" in package.namelist(), "Complete export lost replaced goal definitions"
        revisions = [json.loads(line) for line in package.read("records/goal_revisions.jsonl").splitlines()]
        revisions = sorted((row for row in revisions if row["goal_id"] == goal["id"]), key=lambda row: row["row_version"])
        assert len(revisions) == 5 and {row["tenant_id"] for row in revisions} == {"owner"}
        for row, receipt, kind in zip(revisions, accepted, ["create", "edit", "edit", "archive", "restore"], strict=True):
            _assert_definition(row, receipt, kind)
    other = client.get("/api/exports/portable", headers=identity.gray_app_headers)
    assert other.status_code == 200, other.text
    with ZipFile(BytesIO(other.content)) as package:
        assert json.loads(package.read("manifest.json"))["ledger_id"] == "tester_1"
        assert package.read("records/goal_revisions.jsonl") == b""


def test_archived_history_is_reader_visible_but_stays_ledger_scoped(client, identity):
    _, _, goal = _create(client, identity)
    archived = client.post(f'/api/goals/{goal["public_id"]}/archive', headers=identity.app_headers)
    assert archived.status_code == 200, archived.text
    with SessionLocal.begin() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner"))
        assert member is not None
        member.role = "viewer"
    public_id = goal["public_id"]
    history = _history(client, identity, public_id)
    assert len(history["items"]) == 2
    _assert_definition(history["items"][0], archived.json(), "archive")
    denied = client.post(f"/api/goals/{public_id}/restore", headers=identity.app_headers,
        json={"expected_row_version": archived.json()["row_version"]})
    assert denied.status_code == 403
    assert client.get(f"/api/goals/{public_id}/history", headers=identity.gray_app_headers).status_code == 404
    assert client.get(f"/api/goals/{public_id}/history").status_code == 401


def test_first_edit_of_a_preexisting_row_records_only_the_known_baseline(client, identity):
    public_id = str(uuid4())
    with SessionLocal.begin() as db:
        resolve_write_capability(db)
        db.add(Goal(public_id=public_id, tenant_id="owner", name="既有定义", month="2026-05", category="交通",
            target_amount_cents=1200, home_currency_code="JPY", row_version=7,
            created_at=datetime(2020, 1, 1, tzinfo=UTC), updated_at=datetime(2021, 1, 1, tzinfo=UTC)))
    before = client.get(f"/api/goals/{public_id}", headers=identity.app_headers)
    assert before.status_code == 200 and before.json()["row_version"] == 7
    recorded_after = datetime.now(UTC)
    _, _, edited = _edit(client, identity, before.json(), name="首次可记录修改", target_amount_cents=1800)
    history = _history(client, identity, public_id)
    assert [item["row_version"] for item in history["items"]] == [8, 7]
    _assert_definition(history["items"][0], edited, "edit")
    baseline = history["items"][1]
    _assert_definition(baseline, before.json(), "baseline")
    assert datetime.fromisoformat(baseline["recorded_at"].replace("Z", "+00:00")) >= recorded_after
    assert history["next_before_version"] is None  # No invented versions 1–6 or old change timestamps.


def test_real_web_goal_consumer_links_to_original_definition_history(web_client, identity):
    accepted = _accepted_lifecycle(web_client, identity)
    public_id = accepted[0]["public_id"]
    page = web_client.get("/web/goals", params={"ledger_id": "owner", "month": "2026-06"})
    assert page.status_code == 200, page.text
    assert f'/web/goals/{public_id}/history?' in page.text
    history = web_client.get(f"/web/goals/{public_id}/history", params={"ledger_id": "owner"})
    assert history.status_code == 200, history.text
    assert "原交通上限" in history.text and "六月餐饮上限" in history.text
    assert "2026-05" in history.text and "2026-06" in history.text
    assert "JPY" in history.text and "1200" in history.text and "1800" in history.text


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_failed_history_append_cannot_commit_a_goal_or_its_accepted_receipt(client, identity, monkeypatch, operation):
    _, _, original = _create(client, identity)
    key = str(uuid4())
    url = "/api/goals" if operation == "create" else f'/api/goals/{original["public_id"]}'
    body = {"name": "尚未接受定义", "home_currency_code": "JPY", "target_amount_cents": 1800}
    if operation == "create":
        body.update(month="2026-07", category="餐饮")
    else:
        body["expected_row_version"] = original["row_version"]
    method = "POST" if operation == "create" else "PATCH"

    def refuse(*args, **kwargs):
        raise AppError("state_conflict", status_code=409)

    with monkeypatch.context() as patch:
        patch.setattr(goal_service, "record_goal_revision", refuse)
        failed = client.request(method, url, json=body, headers=_headers(client, identity, key))
    assert failed.status_code == 409, failed.text
    current = client.get(f'/api/goals/{original["public_id"]}', headers=identity.app_headers)
    assert current.status_code == 200 and current.json()["row_version"] == original["row_version"]
    assert current.json()["name"] == original["name"]
    assert len(_history(client, identity, original["public_id"])["items"]) == 1
    with SessionLocal() as db:
        assert db.scalar(select(Goal.id).where(Goal.tenant_id == "owner", Goal.name == body["name"])) is None
        assert db.scalar(select(ApiIdempotencyKey.id).where(ApiIdempotencyKey.tenant_id == "owner",
            ApiIdempotencyKey.idempotency_key == key)) is None
    accepted = client.request(method, url, json=body, headers=_headers(client, identity, key))
    assert accepted.status_code == (201 if operation == "create" else 200), accepted.text
    replay = client.request(method, url, json=body, headers=_headers(client, identity, key))
    assert replay.status_code == accepted.status_code and replay.json() == accepted.json()
    history = _history(client, identity, accepted.json()["public_id"])
    assert len(history["items"]) == (1 if operation == "create" else 2)


def test_recycle_bin_restore_records_the_same_original_definition_and_known_actor(client, identity):
    _, _, goal = _create(client, identity)
    archived = client.post(f'/api/goals/{goal["public_id"]}/archive', headers=identity.app_headers)
    assert archived.status_code == 200, archived.text
    restored = client.post("/api/recycle-bin/restore", headers=identity.app_headers, json={
        "kind": "goal", "resource_id": goal["public_id"], "expected_row_version": archived.json()["row_version"],
    })
    assert restored.status_code == 200, restored.text
    current = client.get(f'/api/goals/{goal["public_id"]}', headers=identity.app_headers)
    assert current.status_code == 200 and current.json()["row_version"] == archived.json()["row_version"] + 1
    history = _history(client, identity, goal["public_id"])
    assert len(history["items"]) == 3
    _assert_definition(history["items"][0], current.json(), "restore")
    with SessionLocal() as db:
        actors = db.scalars(select(GoalRevision.actor_account_id).join(Goal, Goal.id == GoalRevision.goal_id)
            .where(Goal.tenant_id == "owner", Goal.public_id == goal["public_id"])).all()
        assert len(actors) == 3 and actors[0] is not None and actors == [actors[0]] * 3
