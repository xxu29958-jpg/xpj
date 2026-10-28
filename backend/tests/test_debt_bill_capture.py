"""Real HTTP evidence: originals precede suggestions and the original Debt command."""

import hashlib
from dataclasses import replace
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import delete, func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, Debt, DebtBillCapture, Expense, RepaymentDraft
from app.schemas import DebtCreateRequest
from app.services import debt_bill_source_parse
from app.services.debt_bill_parse_service import MockDebtBillProvider
from app.services.file_service import resolve_upload_path_for_tenant
from app.services.idempotency import fingerprint_request
from app.services.original_reference_queries import referenced_upload_paths
from tests._infra.assets import PNG_BYTES
from tests._runtime_protocol import negotiated_headers
from tests.family_ledger_test_support import set_owner_ledger_role


def capture(client, identity, *, creation_key="original-create", capture_key="original-capture"):
    response = client.post("/api/debt-bills",
        headers=negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": capture_key}),
        data={"creation_key": creation_key}, files={"file": ("private-bank.png", PNG_BYTES, "image/png")})
    assert response.status_code == 200, response.text
    return response.json()


def parse(client, identity, source, *, key="original-parse", version=None):
    return client.post(f"/api/debt-bills/{source['public_id']}/parse",
        headers=negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": key}),
        json={"expected_row_version": source["row_version"] if version is None else version})


def create_body(source=None, *, version=None):
    body = {"home_currency_code": "CNY", "direction": "i_owe", "counterparty_type": "external",
            "counterparty_label": "My bank", "principal_amount_cents": 12000}
    if source is not None:
        body["bill_source"] = {"public_id": source["public_id"],
            "expected_row_version": source["row_version"] if version is None else version}
    return body


def create(client, identity, body, *, key="original-create"):
    return client.post("/api/debts", json=body,
        headers=negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": key}))


@pytest.mark.real_db
def test_capture_commits_original_before_provider_and_failed_suggestion_can_be_adopted(client, identity, monkeypatch):
    source = capture(client, identity)
    assert source["input_sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    original_path = None

    class FailedProvider:
        def parse(self, data, media_type):
            nonlocal original_path
            with SessionLocal() as independent:
                accepted = independent.scalar(select(DebtBillCapture))
                assert accepted.public_id == source["public_id"]
                original_path = resolve_upload_path_for_tenant(accepted.image_path, "owner")
                assert original_path.read_bytes() == data
                assert hashlib.sha256(data).hexdigest() == accepted.image_hash
                assert accepted.image_evidence
                assert independent.scalar(select(func.count()).select_from(Debt)) == 0
                assert independent.scalar(select(func.count()).select_from(Expense)) == 0
                assert independent.scalar(select(func.count()).select_from(RepaymentDraft)) == 0
            raise AppError("debt_bill_provider_unavailable", status_code=503)

    monkeypatch.setattr(debt_bill_source_parse, "get_debt_bill_provider", FailedProvider)
    failed = parse(client, identity, source)
    assert failed.status_code == 200, failed.text
    outcome = failed.json()
    assert outcome["status"] == "failed" and outcome["suggestion"] is None
    assert outcome["row_version"] == 2 and original_path.exists()
    # A lost model reply recovers its original outcome without another inference.
    replay = parse(client, identity, source)
    assert replay.json() == outcome
    outcome_read = client.get(f"/api/debt-bills/{source['public_id']}/parse-attempts/original-parse",
        headers=identity.app_headers)
    assert outcome_read.json() == outcome
    body = create_body(source, version=2)
    accepted = create(client, identity, body)
    assert accepted.status_code == 201, accepted.text
    debt = accepted.json()
    assert debt["source_type"] == "manual" and debt["source_id"] is None
    assert debt["principal_amount_cents"] == 12000 and "bill_source" not in debt
    assert create(client, identity, body).json() == debt
    detail = client.get(f"/api/debt-bills/{source['public_id']}", headers=identity.app_headers).json()
    assert detail["adopted_debt_public_id"] == debt["public_id"] and detail["status"] == "confirmed"
    assert detail["row_version"] == 3
    assert capture(client, identity) == source  # capture's stable first receipt, even after adoption
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Debt)) == 1
        assert db.scalar(select(func.count()).select_from(Expense)) == 0


def test_capture_replay_survives_receipt_purge_and_preserves_private_gc_reference(client, identity):
    source = capture(client, identity)
    with SessionLocal.begin() as db:
        row = db.scalar(select(DebtBillCapture))
        reference = row.image_path
        assert reference in referenced_upload_paths(db, "owner")
        db.execute(delete(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == "original-capture"))
    assert capture(client, identity) == source
    lookup = client.get("/api/debt-bills/by-key/original-capture", headers=identity.app_headers)
    assert lookup.status_code == 200 and lookup.json()["public_id"] == source["public_id"]
    rejected = client.post("/api/debt-bills", headers={**identity.app_headers, "Idempotency-Key": "original-capture"},
        data={"creation_key": "different-task"}, files={"file": ("private-bank.png", PNG_BYTES, "image/png")})
    assert rejected.status_code == 422 and rejected.json()["error"] == "idempotency_key_reused"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DebtBillCapture)) == 1
        assert resolve_upload_path_for_tenant(reference, "owner").exists()


def test_source_private_read_and_write_scope_and_version_conflicts(client, identity):
    source = capture(client, identity)
    path = f"/api/debt-bills/{source['public_id']}"
    for suffix in ("", "/original", "/parse-attempts/missing"):
        assert client.get(path + suffix, headers=identity.gray_app_headers).status_code == 404
        assert client.get(path + suffix).status_code == 401
    assert client.get("/api/debt-bills", headers=identity.gray_app_headers).json() == {"captures": []}
    other_task = create(client, identity, create_body(source), key="wrong-create")
    assert other_task.status_code == 422 and other_task.json()["error"] == "debt_bill_task_mismatch"
    stale = create(client, identity, create_body(source, version=9))
    assert stale.status_code == 409 and stale.json()["error"] == "state_conflict"
    set_owner_ledger_role("viewer")
    assert client.get(path + "/original", headers=identity.app_headers).status_code == 200
    assert parse(client, identity, source).status_code == 403
    denied = create(client, identity, create_body(source))
    assert denied.status_code == 403


def test_discard_is_authenticated_versioned_and_replays_without_deleting_original(client, identity):
    source = capture(client, identity)
    body = {"expected_row_version": source["row_version"]}
    headers = negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": "original-discard"})
    assert client.post(f"/api/debt-bills/{source['public_id']}/discard", json=body).status_code == 401
    stale = client.post(f"/api/debt-bills/{source['public_id']}/discard", headers=headers,
        json={"expected_row_version": 99})
    assert stale.status_code == 409
    response = client.post(f"/api/debt-bills/{source['public_id']}/discard", headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected" and response.json()["row_version"] == 2
    assert client.post(f"/api/debt-bills/{source['public_id']}/discard", headers=headers, json=body).json() == response.json()
    assert client.post(f"/api/debt-bills/{source['public_id']}/discard", headers=headers,
        json={"expected_row_version": 2}).status_code == 422
    assert create(client, identity, create_body(source, version=2)).status_code == 409
    assert client.get(f"/api/debt-bills/{source['public_id']}/original", headers=identity.app_headers).status_code == 200
    assert capture(client, identity) == source


def test_parse_replay_and_explicit_retry_are_distinct_versioned_suggestions(client, identity, monkeypatch):
    source = capture(client, identity)
    monkeypatch.setattr(debt_bill_source_parse, "get_debt_bill_provider", MockDebtBillProvider)
    first = parse(client, identity, source)
    assert first.status_code == 200, first.text
    assert first.json()["suggestion"]["merchant"] == "花呗"
    assert parse(client, identity, source, key="other").status_code == 409
    retry = parse(client, identity, source, key="retry", version=2)
    assert retry.status_code == 200 and retry.json()["row_version"] == 3
    assert parse(client, identity, source).json() == first.json()
    assert create(client, identity, create_body(source, version=2)).status_code == 409
    assert create(client, identity, create_body(source, version=3)).status_code == 201


def test_create_failure_rolls_back_source_adoption_and_original_key_can_continue(client, identity):
    source = capture(client, identity)
    invalid = {**create_body(source), "counterparty_type": "member", "counterparty_account_id": 1}
    assert create(client, identity, invalid).status_code == 422
    detail = client.get(f"/api/debt-bills/{source['public_id']}", headers=identity.app_headers).json()
    assert detail["status"] == "pending" and detail["row_version"] == 1
    assert create(client, identity, create_body(source)).status_code == 201


def test_absent_source_keeps_old_create_fingerprint_and_receipt(client, identity):
    body = create_body()
    accepted = create(client, identity, body)
    assert accepted.status_code == 201, accepted.text
    payload = DebtCreateRequest.model_validate(body)
    assert payload.model_dump(mode="json", exclude_unset=True) == body
    with SessionLocal() as db:
        debt = db.scalar(select(Debt))
        row = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.operation == "create_debt"))
        assert row.request_fingerprint == fingerprint_request(operation="create_debt", target_id="original-create",
            body={**body, "actor_account_id": debt.created_by_account_id}, expected_row_version=None)
    assert create(client, identity, body).json() == accepted.json()
    assert create(client, identity, {**body, "bill_source": None}).status_code == 422


def test_old_raw_parse_refuses_before_provider_and_new_capture_validates_bytes(client, identity, monkeypatch):
    def forbidden_provider():
        pytest.fail("unretained raw bytes must never reach inference")
    monkeypatch.setattr(debt_bill_source_parse, "get_debt_bill_provider", forbidden_provider)
    old = client.post("/api/debts/parse-bill", headers=identity.app_headers,
        files={"file": ("old.png", PNG_BYTES, "image/png")})
    assert old.status_code == 409 and old.json()["error"] == "client_upgrade_required"
    bad = client.post("/api/debt-bills", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        data={"creation_key": "task"}, files={"file": ("bad.txt", b"hello", "text/plain")})
    assert bad.status_code == 400 and bad.json()["error"] == "unsupported_file_type"


@pytest.mark.real_db
def test_private_portable_export_includes_retained_source_and_no_storage_paths(client, identity):
    source = capture(client, identity)
    response = client.get("/api/exports/portable", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as package:
        records = package.read("records/debt_bill_captures.jsonl").decode()
        assert source["public_id"] in records and "image_path" not in records
        originals = package.read("originals.jsonl").decode()
        assert "debt_bill_capture:" in originals and '"state":"verified"' in originals
        assert any(name.startswith("originals/") for name in package.namelist())


def test_confirm_cleanup_uses_durable_authority_and_leaves_stable_capture_receipt(client, identity, monkeypatch):
    from app.services import cleanup_service
    settings = replace(cleanup_service.get_settings(), delete_image_after_confirm=True)
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: settings)
    source = capture(client, identity)
    with SessionLocal() as db:
        row = db.scalar(select(DebtBillCapture))
        original = resolve_upload_path_for_tenant(row.image_path, "owner")
    result = create(client, identity, create_body(source))
    assert result.status_code == 201, result.text
    assert not original.exists()
    assert capture(client, identity) == source
    detail = client.get(f"/api/debt-bills/{source['public_id']}", headers=identity.app_headers).json()
    assert detail["original_state"] == "cleaned" and detail["adopted_debt_public_id"] == result.json()["public_id"]
    unavailable = client.get(f"/api/debt-bills/{source['public_id']}/original", headers=identity.app_headers)
    assert unavailable.status_code == 410
    assert unavailable.json()["error"] == "original_cleaned"
    assert unavailable.json()["message"] == "原件已按保留设置清理，来源记录仍保留。"
    with SessionLocal() as db:
        row = db.scalar(select(DebtBillCapture))
        assert row.image_deleted_at is not None and row.attachment_cleanup_request is None


@pytest.mark.real_db
def test_failed_capture_before_commit_rolls_back_receipt_and_removes_unpublished_bytes(client, identity, monkeypatch):
    from app.services import debt_bill_capture_service
    paths = []

    def fail_receipt(db, *_args, **_kwargs):
        source = db.scalar(select(DebtBillCapture))
        paths.append(resolve_upload_path_for_tenant(source.image_path, "owner"))
        raise ValueError("simulated receipt failure before COMMIT")

    with monkeypatch.context() as patch:
        patch.setattr(debt_bill_capture_service, "mark_idempotency_succeeded", fail_receipt)
        with pytest.raises(ValueError, match="simulated receipt failure"):
            capture(client, identity)
    assert paths and all(not path.exists() for path in paths)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DebtBillCapture)) == 0
        assert db.scalar(select(func.count()).select_from(ApiIdempotencyKey)) == 0
    assert capture(client, identity)["capture_key"] == "original-capture"


@pytest.mark.real_db
def test_uncertain_capture_commit_keeps_original_and_recovers_by_original_key(client, identity, monkeypatch):
    from sqlalchemy.orm import Session
    real_commit = Session.commit
    lost = False

    def lose_ack(db):
        nonlocal lost
        is_capture = any(isinstance(row, DebtBillCapture) for row in db.identity_map.values())
        real_commit(db)
        if is_capture and not lost:
            lost = True
            raise OSError("simulated lost COMMIT acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", lose_ack)
        with pytest.raises(OSError, match="lost COMMIT"):
            capture(client, identity)
    assert lost
    recovered = client.get("/api/debt-bills/by-key/original-capture", headers=identity.app_headers)
    assert recovered.status_code == 200 and recovered.json()["original_state"] == "verified"
    replay = capture(client, identity)
    assert replay["public_id"] == recovered.json()["public_id"]


@pytest.mark.real_db
def test_same_ledger_member_cannot_read_adopt_or_export_another_actors_source(client, identity):
    from app.models import Account, AuthToken, Device, LedgerMember
    from app.services.identity_service import hash_secret
    from tests._runtime_protocol import current_protocol_headers
    source = capture(client, identity)
    debt = create(client, identity, create_body(source)).json()
    token = "test-debt-bill-other-member"
    with SessionLocal.begin() as db:
        actor = Account(display_name="Other source actor")
        db.add(actor)
        db.flush()
        device = Device(account_id=actor.id, device_name="Other source device", platform="android")
        db.add(device)
        db.flush()
        db.add(LedgerMember(ledger_id="owner", account_id=actor.id, role="member"))
        db.add(AuthToken(token_hash=hash_secret(token), account_id=actor.id,
                        device_id=device.id, ledger_id="owner", scope="app"))
    headers = current_protocol_headers({"Authorization": f"Bearer {token}"})
    assert client.get(f"/api/debts/{debt['public_id']}", headers=headers).status_code == 200
    assert client.get(f"/api/debt-bills/{source['public_id']}", headers=headers).status_code == 404
    assert client.get(f"/api/debt-bills/{source['public_id']}/original", headers=headers).status_code == 404
    assert client.get("/api/debt-bills", headers=headers).json() == {"captures": []}
    response = client.get("/api/exports/portable", headers=headers)
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as package:
        assert package.read("records/debt_bill_captures.jsonl") == b""
        assert source["public_id"].encode() not in package.read("records/accepted_operations.jsonl")


@pytest.mark.real_db
def test_browser_original_uses_the_same_actor_scope_and_retained_bytes(client, identity):
    from app.routes.web_auth import SESSION_COOKIE_NAME
    from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client
    source = capture(client, identity)
    debt = create(client, identity, create_body(source)).json()
    browser = public_client()
    browser.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity), domain=PUBLIC_HOST, path="/")
    detail = browser.get(f"/web/debts/{debt['public_id']}?ledger_id=owner")
    assert detail.status_code == 200 and "private-bank.png" in detail.text
    original = browser.get(f"/web/debts/{debt['public_id']}/bill-sources/{source['public_id']}/original?ledger_id=owner")
    assert original.status_code == 200 and original.content == PNG_BYTES
    assert original.headers["Cache-Control"] == "no-store"  # The Web session middleware owns this header.
    denied = browser.get(f"/web/debts/{debt['public_id']}/bill-sources/{source['public_id']}/original?ledger_id=tester_1")
    assert denied.status_code == 403  # Existing participant authority refuses the cross-ledger Debt first.
    assert denied.content != PNG_BYTES
