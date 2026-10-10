"""Review accepted definitions and the plan actually used when a period was recorded.

Period labels are not definition effective dates. A late record uses the plan at
recording time; pre-existing associations with no evidence remain explicitly unknown.
"""

import json
from datetime import UTC, date, datetime
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerMember, RecurringItem, RecurringOccurrence, RecurringOccurrenceRevision
from app.services.currency_binding_service import resolve_write_capability
from tests._infra.currency import activate_test_currency_authority
from tests._runtime_protocol import negotiated_headers
from tests.test_recurring_items import _seed_monthly_candidate

pytestmark = pytest.mark.real_db
DEFINITION_FIELDS = ("merchant", "merchant_key", "frequency", "home_currency_code", "baseline_amount_cents",
    "next_expected_date", "status", "source")


def _headers(client, identity, key=None):
    return {**negotiated_headers(client, identity.app_headers), "Idempotency-Key": key or str(uuid4())}


def _definition(receipt):
    return {field: receipt[field] for field in DEFINITION_FIELDS}


def _create(client, identity, currency="JPY"):
    body = {"merchant": "原固定支出", "home_currency_code": currency, "baseline_amount_cents": 1200,
        "next_expected_date": "2026-09-05"}
    key = str(uuid4())
    response = client.post("/api/recurring/items", headers=_headers(client, identity, key), json=body)
    assert response.status_code == 201, response.text
    return body, key, response.json()


def _edit(client, identity, previous, **changes):
    body = {"home_currency_code": previous["home_currency_code"],
        "expected_row_version": previous["row_version"], **changes}
    key = str(uuid4())
    response = client.patch(f'/api/recurring/items/{previous["public_id"]}',
        headers=_headers(client, identity, key), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["row_version"] == previous["row_version"] + 1
    return body, key, response.json()


def _history(client, identity, public_id, **params):
    response = client.get(f"/api/recurring/items/{public_id}/history", headers=identity.app_headers, params=params)
    assert response.status_code == 200, response.text
    history = response.json()
    assert (history["ledger_id"], history["public_id"]) == ("owner", public_id)
    return history


def _payment(client, identity, *, currency="CNY", amount=1200, month="2026-05"):
    response = client.post("/api/expenses/manual", headers=identity.app_headers, json={
        "client_ref": str(uuid4()), "home_currency_code": currency, "amount_cents": amount,
        "merchant": "真实付款", "category": "其他", "expense_time": f"{month}-05T12:00:00Z",
    })
    assert response.status_code == 200, response.text
    return response.json()


def _link(client, identity, series, payment, month="2026-05", version=0):
    body = {"action": "link", "expense_public_id": payment["public_id"],
        "expected_expense_row_version": payment["row_version"], "expected_row_version": version,
        "expected_series_row_version": series["row_version"]}
    key = str(uuid4())
    response = client.put(f'/api/recurring/items/{series["public_id"]}/occurrences/{month}',
        headers=_headers(client, identity, key), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "fulfilled"
    assert (response.json()["expense_public_id"], response.json()["paid_amount_cents"],
        response.json()["paid_home_currency_code"]) == (payment["public_id"], payment["amount_cents"], payment["home_currency"])
    return body, key, response.json()


def _payment_revisions(public_id):
    with SessionLocal() as db:
        return list(db.execute(select(RecurringOccurrenceRevision.period_start,
            RecurringOccurrenceRevision.revision_number, RecurringOccurrenceRevision.previous_expense_id,
            RecurringOccurrenceRevision.expense_id, RecurringOccurrenceRevision.idempotency_key,
            RecurringOccurrenceRevision.created_at).join(RecurringItem,
                RecurringItem.id == RecurringOccurrenceRevision.series_id).where(
                    RecurringItem.tenant_id == "owner", RecurringItem.public_id == public_id)
            .order_by(RecurringOccurrenceRevision.revision_number)))


def _assert_complete_portable_history(client, identity, public_id, accepted):
    response = client.get("/api/exports/portable", headers=identity.app_headers, params={"month": "1999-01"})
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as package:
        assert json.loads(package.read("manifest.json"))["records_complete"] is True
        assert "records/recurring_item_revisions.jsonl" in package.namelist()
        series = next(json.loads(line) for line in package.read("records/recurring_items.jsonl").splitlines()
            if json.loads(line)["public_id"] == public_id)
        revisions = [json.loads(line) for line in package.read("records/recurring_item_revisions.jsonl").splitlines()]
        revisions = sorted((row for row in revisions if row["series_id"] == series["id"]), key=lambda row: row["row_version"])
        assert [row["snapshot"] for row in revisions] == [_definition(row) for row in accepted]
        assert [row["row_version"] for row in revisions] == [row["row_version"] for row in accepted]
        latest = _history(client, identity, public_id)
        assert {row["row_version"]: datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
            for row in revisions} == {row["row_version"]: datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
                for row in latest["items"]}


def test_original_receipts_lifecycle_history_stable_pages_and_complete_portable_stay_ledger_scoped(client, identity):
    create_body, create_key, original = _create(client, identity)
    body, key, edited = _edit(client, identity, original, merchant="修改后固定支出",
        baseline_amount_cents=1800, next_expected_date="2026-10-09")
    _, _, later = _edit(client, identity, edited, baseline_amount_cents=2200)
    path = f'/api/recurring/items/{original["public_id"]}'
    replay = client.patch(path, headers=_headers(client, identity, key), json=body)
    assert replay.status_code == 200 and replay.json() == edited
    replay_create = client.post("/api/recurring/items", headers=_headers(client, identity, create_key), json=create_body)
    assert replay_create.status_code == 201 and replay_create.json() == original
    stale = client.patch(path, headers=_headers(client, identity), json=body)
    assert stale.status_code == 409
    relabel = client.patch(path, headers=_headers(client, identity), json={
        "expected_row_version": later["row_version"], "home_currency_code": "CNY", "baseline_amount_cents": 2200})
    assert relabel.status_code == 409 and relabel.json()["error"] == "recurring_currency_conflict"
    accepted = [original, edited, later]
    for action in ("pause", "resume", "archive", "restore"):
        payload = {} if action == "archive" else {"expected_row_version": accepted[-1]["row_version"]}
        response = client.post(f"{path}/{action}", headers=identity.app_headers, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["row_version"] == accepted[-1]["row_version"] + 1
        accepted.append(response.json())
        if action in {"archive", "restore"}:
            repeat = client.post(f"{path}/{action}", headers=identity.app_headers, json=payload)
            assert repeat.status_code == 200 and repeat.json()["row_version"] == accepted[-1]["row_version"]
    first = _history(client, identity, original["public_id"], limit=2)
    _, _, newest = _edit(client, identity, accepted[-1], baseline_amount_cents=2500)
    items = list(first["items"])
    cursor = first["next_before_version"]
    for _ in range(3):
        assert cursor is not None
        page = _history(client, identity, original["public_id"], limit=2, before_version=cursor)
        assert page == _history(client, identity, original["public_id"], limit=2, before_version=cursor)
        items.extend(page["items"])
        cursor = page["next_before_version"]
    assert cursor is None
    assert len(items) == 7
    for item, receipt, kind in zip(items, reversed(accepted),
        ("restore", "archive", "resume", "pause", "edit", "edit", "create"), strict=True):
        assert (item["row_version"], item["change_kind"], item["snapshot"]) == (receipt["row_version"], kind, _definition(receipt))
        assert datetime.fromisoformat(item["recorded_at"].replace("Z", "+00:00")).tzinfo is not None
    _assert_complete_portable_history(client, identity, original["public_id"], [*accepted, newest])
    with SessionLocal.begin() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner"))
        assert member is not None
        member.role = "viewer"
    assert len(_history(client, identity, original["public_id"])["items"]) == 8
    assert client.post(f"{path}/archive", headers=identity.app_headers).status_code == 403
    assert client.get(f"{path}/history", headers=identity.gray_app_headers).status_code == 404
    assert client.get(f"{path}/history").status_code == 401
    other = client.get("/api/exports/portable", headers=identity.gray_app_headers)
    assert other.status_code == 200
    with ZipFile(BytesIO(other.content)) as package:
        assert package.read("records/recurring_item_revisions.jsonl") == b""


def test_real_candidate_observations_definition_edits_and_payment_revisions_have_separate_owners(client, identity, monkeypatch):
    monkeypatch.setattr("app.services.insights_service.now_utc", lambda: datetime(2026, 8, 31, 12, tzinfo=UTC))
    _seed_monthly_candidate()
    candidates = client.get("/api/insights/recurring-candidates?timezone=UTC", headers=identity.app_headers)
    assert candidates.status_code == 200, candidates.text
    observed = candidates.json()["items"][0]
    body = {"merchant": observed["merchant"], "home_currency_code": observed["home_currency_code"],
        "amount_cents": observed["amount_cents"], "occurrence_count": 999,
        "last_seen_at": "2099-01-01T00:00:00Z", "confidence": "low", "next_expected_date": "2026-09-05"}
    adoption_key = str(uuid4())
    adopted = client.post("/api/recurring/from-candidate?timezone=UTC", headers={**identity.app_headers, "Idempotency-Key": adoption_key}, json=body)
    assert adopted.status_code == 200, adopted.text
    series = adopted.json()
    provenance = {field: series[field] for field in ("last_amount_cents", "occurrence_count", "last_seen_at", "confidence", "source")}
    assert provenance == {"last_amount_cents": observed["amount_cents"], "occurrence_count": observed["occurrence_count"],
        "last_seen_at": observed["last_seen_at"], "confidence": observed["confidence"], "source": "candidate"}
    repeat = client.post("/api/recurring/from-candidate?timezone=UTC", headers={**identity.app_headers, "Idempotency-Key": adoption_key}, json=body)
    assert repeat.status_code == 200 and repeat.json()["row_version"] == series["row_version"]
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.tenant_id == "owner", Expense.merchant == "ChatGPT Plus")
            .order_by(Expense.id.desc()))
        payment_id = expense.id
    payment = client.get(f"/api/expenses/{payment_id}", headers=identity.app_headers).json()
    link_body, link_key, linked = _link(client, identity, series, payment)
    payments_before = _payment_revisions(series["public_id"])
    _, _, edited = _edit(client, identity, series, baseline_amount_cents=24000, next_expected_date="2026-10-09")
    assert {field: edited[field] for field in provenance} == provenance
    assert _payment_revisions(series["public_id"]) == payments_before
    clear = client.put(f'/api/recurring/items/{series["public_id"]}/occurrences/2026-05',
        headers=_headers(client, identity), json={"action": "clear", "expected_row_version": linked["row_version"],
            "expected_series_row_version": edited["row_version"]})
    assert clear.status_code == 200 and clear.json()["state"] == "unfulfilled"
    replay = client.put(f'/api/recurring/items/{series["public_id"]}/occurrences/2026-05',
        headers=_headers(client, identity, link_key), json=link_body)
    assert replay.status_code == 200 and replay.json() == linked
    payments = _payment_revisions(series["public_id"])
    assert payments[0] == payments_before[0] and len(payments) == 2
    assert (payments[0].previous_expense_id, payments[0].expense_id) == (None, payment_id)
    assert (payments[1].previous_expense_id, payments[1].expense_id) == (payment_id, None)
    assert client.get(f"/api/expenses/{payment_id}", headers=identity.app_headers).json() == payment
    history = _history(client, identity, series["public_id"])
    assert [(row["row_version"], row["change_kind"], row["snapshot"]) for row in history["items"]] == [
        (edited["row_version"], "edit", _definition(edited)), (series["row_version"], "create", _definition(series))]


@pytest.mark.currency_binding_unbound
def test_recorded_yen_period_keeps_its_definition_while_late_old_month_uses_the_recording_time_plan(client, identity):
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "JPY")
    _, _, original = _create(client, identity)
    payment = _payment(client, identity, currency="JPY")
    captured_after = datetime.now(UTC)
    body, key, linked = _link(client, identity, original, payment)
    payments_before = _payment_revisions(original["public_id"])
    _, _, edited = _edit(client, identity, original, merchant="后来计划名称",
        baseline_amount_cents=1800, next_expected_date="2026-10-09")
    path = f'/api/recurring/items/{original["public_id"]}/occurrences/2026-05'
    current = client.get(path, headers=identity.app_headers)
    assert current.status_code == 200 and current.json()["state"] == "fulfilled"
    assert (current.json()["paid_amount_cents"], current.json()["paid_home_currency_code"], current.json()["row_version"]) == (1200, "JPY", linked["row_version"])
    assert _payment_revisions(original["public_id"]) == payments_before
    assert client.get(f'/api/expenses/{payment["id"]}', headers=identity.app_headers).json() == payment
    replay = client.put(path, headers=_headers(client, identity, key), json=body)
    assert replay.status_code == 200 and replay.json() == linked
    assert "recorded_definition" in linked
    recorded = linked["recorded_definition"]
    assert recorded["series_row_version"] == original["row_version"] and recorded["snapshot"] == _definition(original)
    assert datetime.fromisoformat(recorded["recorded_at"].replace("Z", "+00:00")) >= captured_after
    assert current.json()["recorded_definition"] == recorded
    assert client.get(path, headers=identity.app_headers).json()["recorded_definition"] == recorded
    cleared = client.put(path, headers=_headers(client, identity), json={"action": "clear",
        "expected_row_version": linked["row_version"], "expected_series_row_version": edited["row_version"]})
    assert cleared.status_code == 200 and cleared.json()["state"] == "unfulfilled"
    assert cleared.json()["recorded_definition"] == recorded
    _, _, relinked = _link(client, identity, edited, payment, version=cleared.json()["row_version"])
    assert relinked["recorded_definition"] == recorded  # Later associations do not reassign the first recording basis.
    assert client.get(f'/api/expenses/{payment["id"]}', headers=identity.app_headers).json() == payment
    # This is an April label recorded later: not a claim that April used the new plan.
    late_payment = _payment(client, identity, currency="JPY", amount=1800, month="2026-04")
    late_after = datetime.now(UTC)
    _, _, late = _link(client, identity, edited, late_payment, month="2026-04")
    assert late["recorded_definition"]["snapshot"] == _definition(edited)
    assert late["recorded_definition"]["series_row_version"] == edited["row_version"]
    assert datetime.fromisoformat(late["recorded_definition"]["recorded_at"].replace("Z", "+00:00")) >= late_after


def test_preexisting_payment_association_does_not_invent_its_unknown_original_definition(client, identity):
    payment = _payment(client, identity)
    public_id = str(uuid4())
    with SessionLocal.begin() as db:
        resolve_write_capability(db)
        series = RecurringItem(public_id=public_id, tenant_id="owner", merchant_key="legacy", merchant_name="既有当前定义",
            frequency="monthly", home_currency_code="CNY", baseline_amount_cents=9000, last_amount_cents=9000,
            next_expected_date=date(2026, 9, 5), status="active", source="manual", row_version=7)
        db.add(series)
        db.flush()
        db.add(RecurringOccurrence(tenant_id="owner", series_id=series.id, period_start=date(2026, 5, 1),
            expense_id=payment["id"], row_version=3, updated_at=datetime(2020, 1, 1, tzinfo=UTC)))
    path = f"/api/recurring/items/{public_id}/occurrences/2026-05"
    before = client.get(path, headers=identity.app_headers)
    assert before.status_code == 200 and before.json()["state"] == "fulfilled"
    assert (before.json()["row_version"], before.json()["paid_amount_cents"]) == (3, 1200)
    _, _, edited = _edit(client, identity, {"public_id": public_id, "home_currency_code": "CNY", "row_version": 7},
        baseline_amount_cents=6000)
    after = client.get(path, headers=identity.app_headers)
    assert after.status_code == 200 and after.json()["expense_public_id"] == payment["public_id"]
    assert (after.json()["row_version"], after.json()["paid_amount_cents"]) == (3, 1200)
    assert client.get(f'/api/expenses/{payment["id"]}', headers=identity.app_headers).json() == payment
    assert "recorded_definition" in before.json() and before.json()["recorded_definition"] is None
    assert "recorded_definition" in after.json() and after.json()["recorded_definition"] is None
    cleared = client.put(path, headers=_headers(client, identity), json={"action": "clear",
        "expected_row_version": 3, "expected_series_row_version": edited["row_version"]})
    assert cleared.status_code == 200 and cleared.json()["state"] == "unfulfilled"
    assert cleared.json()["recorded_definition"] is None
    _, _, relinked = _link(client, identity, edited, payment, version=cleared.json()["row_version"])
    assert relinked["recorded_definition"] is None  # Reconnection cannot manufacture unknown original evidence.
    history = _history(client, identity, public_id)
    assert [(row["row_version"], row["change_kind"]) for row in history["items"]] == [(8, "edit"), (7, "baseline")]
    assert history["items"][0]["snapshot"] == _definition(edited)
    assert history["items"][1]["snapshot"]["baseline_amount_cents"] == 9000
