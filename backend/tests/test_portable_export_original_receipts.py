"""Accepted original producers retain links without exposing storage paths."""

import json
from datetime import UTC, datetime
from zipfile import ZipFile

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.sql import visitors

from app import models as m
from app.services.portable_export_archive import _receipt_record, create_portable_archive
from app.services.portable_export_queries import portable_original_history_query
from app.tenants import AuthContext

AUTH = AuthContext(account_id=7, account_public_id="actor", account_name="Actor",
    ledger_id="selected", ledger_name="Selected", device_id=1, device_public_id="device",
    device_name="Device", role="viewer", scope="app")


@pytest.fixture
def records():
    statement = portable_original_history_query(AUTH)
    engine = create_engine("sqlite://")
    metadata = MetaData()
    sources = {node.name: node for node in visitors.iterate(statement) if isinstance(node, Table)}
    tables = {name: Table(name, metadata, *(
        Column(column.name, Integer if isinstance(column.type, Integer) else String)
        for column in source.columns)) for name, source in sources.items()}
    metadata.create_all(engine)
    with engine.begin() as connection:
        yield connection, tables
    engine.dispose()


def _seed(records, model, **values):
    records[0].execute(records[1][model.__tablename__].insert().values(**values))


@pytest.mark.parametrize("upload_actor", [7, 8])
def test_upload_and_original_command_receipts_use_the_matching_current_original(records, upload_actor):
    digest = "a" * 64
    _seed(records, m.Expense, id=1, public_id="bill", tenant_id="selected",
        image_path="current.png", image_hash=digest)
    _seed(records, m.BackgroundTask, id=1, public_id="task", tenant_id="selected",
        initiated_by_account_id=upload_actor)
    receipts = (
        (1, "upload_receipt", "bill", {"id": 1, "public_id": "bill",
            "enrichment_task_public_id": "task", "image_hash": digest}),
        (2, "expense", "1", {"operation": "verify_original", "expense_id": 1,
            "public_id": "bill", "sha256": digest}),
    )
    for id_, resource_type, resource_id, body in receipts:
        _seed(records, m.ApiIdempotencyKey, id=id_, tenant_id="selected", status="succeeded",
            resource_type=resource_type, resource_id=resource_id, response_body=json.dumps(body))

    rows = records[0].execute(portable_original_history_query(AUTH)).mappings().all()

    assert [(row["accepted_operation_id"], row["expense_id"], row["image_path"], row["image_hash"])
        for row in rows] == [(1, 1, "current.png", digest), (2, 1, "current.png", digest)]


def test_receipt_digest_mismatch_never_borrows_the_current_original(records):
    _seed(records, m.Expense, id=1, public_id="bill", tenant_id="selected",
        image_path="current.png", image_hash="b" * 64)
    body = {"operation": "replenish_original", "expense_id": 1,
        "public_id": "bill", "sha256": "a" * 64}
    _seed(records, m.ApiIdempotencyKey, id=1, tenant_id="selected", status="succeeded",
        resource_type="expense", resource_id="1", response_body=json.dumps(body))

    row = records[0].execute(portable_original_history_query(AUTH)).mappings().one()

    assert row["image_path"] is None
    assert row["image_hash"] == "a" * 64


@pytest.mark.parametrize(("resource_type", "body", "expense_id"), [
    ("upload_receipt", {"id": 1, "public_id": "bill", "image_hash": "a" * 64}, 1),
    ("expense", {"operation": "verify_original", "expense_id": 1,
        "public_id": "bill", "sha256": "a" * 64}, 1),
])
def test_accepted_producer_receipt_points_to_its_original_index_row(resource_type, body, expense_id):
    receipt = _receipt_record({"id": 9, "resource_type": resource_type, "response_body": body})

    assert receipt["response_body"]["original_reference_id"] == f"expense:{expense_id}:accepted:9"
    assert "image_path" not in receipt["response_body"]


def test_upload_receipt_keeps_shared_evidence_without_private_task_or_runtime_diagnostics():
    body = {"id": 1, "public_id": "bill", "image_hash": "a" * 64, "upload_size_bytes": 123,
        "status": "pending", "enrichment_task_public_id": "private-task", "duration_ms": 500,
        "timing_ms": {"hash": 40, "database": 80}}
    for omission, expected_task in ((None, "private-task"), ("personal_task_scope", None)):
        receipt = _receipt_record({"id": 9, "resource_type": "upload_receipt", "response_body": body,
            "response_body_redaction_reason": omission})["response_body"]
        assert receipt["original_reference_id"] == "expense:1:accepted:9"
        assert receipt["image_hash"] == "a" * 64 and receipt["upload_size_bytes"] == 123
        assert receipt["status"] == "pending"
        assert receipt.get("enrichment_task_public_id") == expected_task
        assert not {"duration_ms", "timing_ms"} & receipt.keys()
    assert body["enrichment_task_public_id"] == "private-task"


def test_digest_only_receipt_is_unavailable_instead_of_claiming_no_original():
    digest = "a" * 64
    receipt = {"id": 9, "resource_type": "expense", "response_body": {
        "operation": "verify_original", "expense_id": 1, "public_id": "bill", "sha256": digest}}
    historical = {"accepted_operation_id": 9, "expense_id": 1,
        "image_path": None, "image_hash": digest}

    with create_portable_archive(ledger_id="selected", snapshot_at=datetime(2026, 9, 20, tzinfo=UTC),
            account_public_id="actor", sections=[("accepted_operations", [receipt])], originals=[],
            historical_originals=[historical]) as result, ZipFile(result.path) as package:
        exported = json.loads(package.read("records/accepted_operations.jsonl"))["response_body"]
        original = json.loads(package.read("originals.jsonl"))

    assert exported["original_reference_id"] == "expense:1:accepted:9"
    assert original["state"] == "unavailable"
    assert original["expected_sha256"] == digest
