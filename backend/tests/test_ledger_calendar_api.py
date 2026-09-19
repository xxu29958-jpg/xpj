"""Real HTTP/PG closure for calendar changes and original offline time intent."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Ledger, LedgerMember


def test_rule_change_preserves_original_receipt_and_captured_old_input(client, identity):
    headers = identity.app_headers
    path = "/api/ledgers/owner/calendar"
    first = client.get(path, headers=headers)
    assert first.status_code == 200
    original_rule = first.json()
    intent = {"precision": "date_only", "calendar_revision": original_rule["revision"],
        "user_local_date": "2026-04-30"}
    payload = {"client_ref": "calendar-original", "home_currency_code": "CNY", "amount_cents": 100,
        "time_input": intent}
    accepted = client.post("/api/expenses/manual", headers=headers, json=payload)
    assert accepted.status_code == 200, accepted.text
    original = accepted.json()
    assert original["accounting_time"]["accounting_date"] == "2026-04-30"
    assert original["expense_time"] is None

    changed_zone = "UTC" if original_rule["timezone_name"] != "UTC" else "Asia/Shanghai"
    change = {"timezone_name": changed_zone, "expected_revision": original_rule["revision"]}
    change_headers = {**headers, "Idempotency-Key": "calendar-rule-attempt"}
    changed = client.post(path, headers=change_headers, json=change)
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == original_rule["revision"] + 1
    assert client.post(path, headers=change_headers, json=change).json() == changed.json()
    assert client.get(path, headers=headers, params={"revision": original_rule["revision"]}).json() == original_rule
    replay = client.post("/api/expenses/manual", headers=headers, json=payload)
    assert replay.status_code == 200 and replay.json() == original

    late = client.post("/api/expenses/manual", headers=headers, json={**payload, "client_ref": "calendar-offline-late"})
    assert late.status_code == 200, late.text
    assert late.json()["accounting_time"] == original["accounting_time"]
    for zone in ("UTC", "Asia/Shanghai", "America/Los_Angeles"):
        page = client.get("/api/expenses/confirmed", headers=headers, params={"month": "2026-04", "timezone": zone})
        assert page.status_code == 200, page.text
        assert page.json()["calendar_revision"] == changed.json()["revision"]
        assert {row["root"]["id"] for row in page.json()["items"]} >= {original["id"], late.json()["id"]}


def test_member_and_viewer_can_read_but_cannot_reinterpret_shared_calendar(client, identity):
    path = "/api/ledgers/owner/calendar"
    assert client.get(path).status_code == 401
    rule = client.get(path, headers=identity.app_headers).json()
    for role in ("member", "viewer"):
        with SessionLocal() as db:
            ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
            member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner",
                LedgerMember.account_id == ledger.owner_account_id))
            member.role = role
            db.commit()
        assert client.get(path, headers=identity.app_headers).status_code == 200
        response = client.post(path, headers={**identity.app_headers, "Idempotency-Key": f"calendar-{role}"},
            json={"expected_revision": rule["revision"], "timezone_name": "UTC"})
        assert response.status_code == 403


def test_new_ledger_has_rule_before_any_financial_command(client, identity):
    created = client.post("/api/ledgers", headers=identity.admin_headers, json={"name": "新日历账本"})
    assert created.status_code == 201
    rule = client.get(f"/api/ledgers/{created.json()['ledger_id']}/calendar", headers=identity.app_headers)
    assert rule.status_code == 200 and rule.json()["revision"] == 1
