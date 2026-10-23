"""Successful original choices affect independent drafts, never confirmed money."""

import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AlgorithmDecision, Expense, LedgerLearningEvent
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_service._ocr_facts import apply_ocr_result_and_append_fact
from app.services.ocr_service import OcrResult
from tests._runtime_protocol import negotiated_headers


def _image(identity, *, day=18, family="a", tenant="owner", printed_offset=""):
    with SessionLocal() as db:
        resolve_write_capability(db)
        expense = Expense(tenant_id=tenant, source="pytest", status="pending", raw_text="",
            home_currency_code="CNY", original_currency_code="CNY", original_amount_minor=2500,
            amount_cents=2500, merchant="便利店", image_hash=family * 64)
        db.add(expense)
        db.flush()
        raw = f"便利店\n支付金额：25.00\n支付时间：2026-10-{day} 12:30{printed_offset}\n消费时间：2026-10-{day} 12:20{printed_offset}"
        apply_ocr_result_and_append_fact(db, expense=expense, result=OcrResult(raw_text=raw, confidence=0.9),
            provider_name="mock", timezone_name="Asia/Shanghai")
        db.commit()
        return expense.id


def _choose(client, identity, expense_id, *, choice=None, day=None, stale=False, index=-1):
    url = f"/api/expenses/{expense_id}"
    before = client.get(url, headers=identity.app_headers).json()
    candidate = before["recognition_time"]["candidates"][index]
    selected = choice or {"evidence_public_id": candidate["evidence_public_id"], "candidate_id": candidate["id"],
        "parser_version": candidate["parser_version"], "source": candidate["source"]}
    date = day or candidate["local_value"][:10]
    offset = candidate["source_utc_offset_seconds"]
    instant = datetime.fromisoformat(date + candidate["local_value"][10:]).replace(
        tzinfo=timezone(timedelta(seconds=offset))).astimezone(UTC).isoformat()
    body = {"expected_row_version": before["row_version"] - int(stale), "recognition_time_choice": selected,
        "time_input": {"precision": "instant", "calendar_revision": before["accounting_time"]["calendar_revision"],
            "user_local_date": date, "instant_utc": instant,
            "source_timezone": candidate["source_timezone"], "source_utc_offset_seconds": offset}}
    headers = negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())})
    response = client.patch(url, headers=headers, json=body)
    return response, url, headers, body, candidate


def test_choice_survives_replay_and_reorders_a_new_case_then_withdraws(client, identity):
    from app.services.learning_service._cleanup import cleanup_expired_learning_events
    from app.services.learning_service._withdrawal import withdraw_feedback
    from app.services.time_service import now_utc

    first, second = _image(identity), _image(identity, day=19, family="b")
    original = client.get(f"/api/expenses/{second}", headers=identity.app_headers).json()
    response, url, headers, body, chosen = _choose(client, identity, first)
    assert response.status_code == 200, response.json()
    assert client.patch(url, headers=headers, json=body).json() == response.json()
    with SessionLocal() as db:
        event = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == first)).one()
        event_id = event.public_id
        data = json.loads(event.after_payload)
        assert event.event_type == "accept" and event.retention_days == 0
        assert data["modified_components"] == [] and data["candidate_id"] == chosen["id"]
        assert data["_learning_qualified"]
    later = client.get(f"/api/expenses/{second}", headers=identity.app_headers).json()
    assert later["recognition_time"]["candidates"][0]["role"] == "consumption"
    assert "明确选择" in later["recognition_time"]["candidates"][0]["explanation"]
    for field in ("expense_time", "accounting_time", "amount_cents", "original_amount_minor", "status", "row_version"):
        assert later[field] == original[field]
    with SessionLocal() as db:
        withdraw_feedback(db, tenant_id="owner", public_id=event_id)
        db.commit()
        cleanup_expired_learning_events(db, tenant_id="owner", now=now_utc() + timedelta(days=400))
    assert client.get(f"/api/expenses/{second}", headers=identity.app_headers).json()["recognition_time"] == original["recognition_time"]
    with SessionLocal() as db:
        assert db.query(AlgorithmDecision).filter_by(subject_id=second,
            decision_type="recognition_time_choice", status="active").count() == 0


@pytest.mark.parametrize("problem", ["foreign", "version", "stale", "accounting_date"])
def test_invalid_source_or_accounting_intent_never_becomes_a_time_label(client, identity, problem):
    expense_id = _image(identity)
    before = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
    candidate = before["recognition_time"]["candidates"][-1]
    choice = {"evidence_public_id": candidate["evidence_public_id"], "candidate_id": candidate["id"],
        "parser_version": candidate["parser_version"], "source": "image"}
    if problem == "foreign":
        other = _image(identity, tenant="tester_1")
        foreign = client.get(f"/api/expenses/{other}", headers=identity.gray_app_headers).json()["recognition_time"]["candidates"][-1]
        choice.update(evidence_public_id=foreign["evidence_public_id"], candidate_id=foreign["id"])
    if problem == "version":
        choice["parser_version"] = "different-parser"
    response, *_ = _choose(client, identity, expense_id, choice=choice,
        day="2026-10-17" if problem == "accounting_date" else None, stale=problem == "stale")
    assert response.status_code == (409 if problem == "stale" else 200), response.json()
    with SessionLocal() as db:
        events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == expense_id)))
        if problem != "accounting_date":
            assert not events
        else:
            payload = json.loads(events[0].after_payload)
            assert payload["intent"] == "bookkeeping" and not payload["_learning_qualified"]
            assert payload["modified_components"] == ["day"]


def test_owner_can_pause_withdraw_and_isolate_time_memory(client, identity):
    from app.main import app
    from app.routes.owner_console._shared import _require_local
    from app.services.learning_service._algorithm_registry import RECOGNITION_TIME_CHOICE

    first, second = _image(identity), _image(identity, day=19, family="b")
    assert _choose(client, identity, first)[0].status_code == 200
    url = f"/api/expenses/{second}"
    learned = client.get(url, headers=identity.app_headers).json()["recognition_time"]
    policy = {"ledger_id": "owner", "decision_type": RECOGNITION_TIME_CHOICE.decision_type,
        "algorithm_version": RECOGNITION_TIME_CHOICE.current_version}
    app.dependency_overrides[_require_local] = lambda: None
    try:
        response = client.post("/owner/algorithm-versions/policy",
            data={**policy, "axis": "new_suggestions", "enabled": "false"})
        assert response.status_code == 200 and "原件时间选择" in response.text
        assert client.get(url, headers=identity.app_headers).json()["recognition_time"] == learned
        third = _image(identity, day=20, family="c")
        fresh = client.get(f"/api/expenses/{third}", headers=identity.app_headers).json()["recognition_time"]
        assert all("明确选择" not in row["explanation"] for row in fresh["candidates"])
        assert client.post("/owner/algorithm-versions/withdraw", data=policy).status_code == 200
        assert all("明确选择" not in row["explanation"] for row in
            client.get(url, headers=identity.app_headers).json()["recognition_time"]["candidates"])
        assert client.post("/owner/algorithm-versions/policy",
            data={**policy, "axis": "training", "enabled": "false"}).status_code == 200
        assert client.post("/owner/algorithm-versions/policy",
            data={**policy, "axis": "new_suggestions", "enabled": "true"}).status_code == 200
        assert client.get(f"/api/expenses/{third}", headers=identity.app_headers).json()["recognition_time"] == fresh
    finally:
        app.dependency_overrides.pop(_require_local, None)


def test_replaced_source_fact_stops_contributing_even_with_same_image(client, identity):
    first, second = _image(identity), _image(identity, day=19, family="b")
    assert _choose(client, identity, first)[0].status_code == 200
    url = f"/api/expenses/{second}"
    assert "明确选择" in client.get(url, headers=identity.app_headers).json()["recognition_time"]["candidates"][0]["explanation"]
    with SessionLocal() as db:
        resolve_write_capability(db)
        source = db.get(Expense, first)
        apply_ocr_result_and_append_fact(db, expense=source,
            result=OcrResult(raw_text="便利店\n支付金额25.00\n打印时间2026-10-18 12:20", confidence=0.9),
            provider_name="mock", timezone_name="Asia/Shanghai")
        db.commit()
    assert all("明确选择" not in row["explanation"] for row in
        client.get(url, headers=identity.app_headers).json()["recognition_time"]["candidates"])


def test_later_explicit_choice_supersedes_without_resurrecting_the_old_revision(client, identity):
    from app.services.learning_service._withdrawal import withdraw_feedback

    first, second = _image(identity), _image(identity, day=19, family="b")
    assert _choose(client, identity, first)[0].status_code == 200
    assert _choose(client, identity, first, index=0)[0].status_code == 200
    later = client.get(f"/api/expenses/{second}", headers=identity.app_headers).json()["recognition_time"]
    assert later["candidates"][0]["role"] == "payment" and "明确选择" in later["candidates"][0]["explanation"]
    with SessionLocal() as db:
        events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == first)
            .order_by(LedgerLearningEvent.id)))
        assert len(events) == 2
        before, after = (json.loads(row.after_payload) for row in events)
        assert before["_feedback_revision"] == 1 and before["selected"]["role"] == "consumption"
        assert after["_feedback_revision"] == 2 and after["_supersedes_event_public_id"] == events[0].public_id
        withdraw_feedback(db, tenant_id="owner", public_id=events[1].public_id)
        db.commit()
    assert all("明确选择" not in row["explanation"] for row in
        client.get(f"/api/expenses/{second}", headers=identity.app_headers).json()["recognition_time"]["candidates"])


def test_changed_printed_offset_invalidates_the_original_time_choice(client, identity):
    first = _image(identity, printed_offset="+08:00")
    second = _image(identity, day=19, family="b", printed_offset="+08:00")
    response, url, _, body, _ = _choose(client, identity, first)
    assert response.status_code == 200, response.json()
    assert "明确选择" in client.get(f"/api/expenses/{second}", headers=identity.app_headers).json()["recognition_time"]["candidates"][0]["explanation"]
    body.pop("recognition_time_choice")
    body["expected_row_version"] = response.json()["row_version"]
    body["time_input"]["source_utc_offset_seconds"] = 32400
    changed = client.patch(url, json=body,
        headers=negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())}))
    assert changed.status_code == 200, changed.json()
    assert all("明确选择" not in row["explanation"] for row in
        client.get(f"/api/expenses/{second}", headers=identity.app_headers).json()["recognition_time"]["candidates"])


def test_pending_list_reads_time_cases_once_and_refreshes_after_withdrawal(client, identity):
    from sqlalchemy import event

    from app.database import engine
    from app.services.learning_service._withdrawal import withdraw_feedback

    first = _image(identity)
    assert _choose(client, identity, first)[0].status_code == 200
    targets = [_image(identity, day=19, family=f"{index:02x}") for index in range(12)]
    reads = []

    def observe(_connection, _cursor, statement, parameters, _context, _many):
        if (statement.startswith("SELECT") and "FROM ledger_learning_events" in statement
                and "LIMIT" in statement and "recognition_time_choice" in parameters.values()):
            reads.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        response = client.get("/api/expenses/pending", headers=identity.app_headers)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json() if row["id"] in targets}
    assert len(rows) == 12
    assert all(row["recognition_time"]["candidates"][0]["role"] == "consumption" for row in rows.values())
    assert all(row["amount_cents"] == 2500 and row["status"] == "pending" for row in rows.values())
    assert len(reads) == 1, f"One pending refresh scanned the actor's time cases {len(reads)} times"
    with SessionLocal() as db:
        source = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == first)).one()
        withdraw_feedback(db, tenant_id="owner", public_id=source.public_id)
        db.commit()
    refreshed = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert refreshed.status_code == 200, refreshed.text
    assert all("明确选择" not in candidate["explanation"]
        for row in refreshed.json() if row["id"] in targets for candidate in row["recognition_time"]["candidates"])
