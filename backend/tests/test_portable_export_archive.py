"""Portable output preserves surviving records while identifying unavailable evidence."""

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import partial
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pytest

from app.errors import AppError
from app.services import original_read_service, portable_export_archive

WHEN = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)


def _rows():
    return [
        ("expenses", iter([{"id": 1, "public_id": "bill", "status": "pending",
            "original_currency_code": "JPY", "original_amount_minor": 9007199254740993,
            "exchange_rate_to_cny": Decimal("0.04876543"), "accounting_date": date(2026, 8, 31),
            "image_path": "uploads/owner/original.png", "thumbnail_path": None,
            "attachment_cleanup_request": None}])),
        ("expense_revisions", iter([{"id": 7, "expense_id": 1, "revision": 2, "reason": "保留更正"}])),
        ("debt_adjustments", iter([{"id": 8, "debt_id": 4, "amount_cents": -50}])),
        ("goals", iter([{"id": 9, "status": "archived", "goal_type": "debt_repayment"}])),
    ]


def _original(expense_id, reference, digest=None, deleted_at=None):
    return {"id": expense_id, "public_id": f"bill-{expense_id}", "image_path": reference,
        "image_hash": digest, "image_deleted_at": deleted_at, "attachment_cleanup_request": None}


def _install_files(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    source.write_bytes(b"stored original bytes")

    def resolve(reference, _ledger):
        if reference == "missing":
            raise AppError("image_not_found", status_code=404)
        return source, "image/png"

    monkeypatch.setattr(original_read_service, "resolve_protected_image", resolve)
    return source


def test_package_retains_nonconfirmed_history_plans_and_original_identity(tmp_path, monkeypatch):
    source = _install_files(tmp_path, monkeypatch)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with portable_export_archive.create_portable_archive(ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=_rows(), originals=iter([_original(1, "available", digest), _original(2, "missing", digest)])) as result:
        with ZipFile(result.path) as package:
            manifest = json.loads(package.read("manifest.json"))
            expense = json.loads(package.read("records/expenses.jsonl"))
            observations = [json.loads(line) for line in package.read("originals.jsonl").splitlines()]
            assert manifest["records_complete"] is True and manifest["originals_complete"] is False
            assert manifest["includes_client_unsubmitted_intents"] is False
            assert expense["status"] == "pending"
            assert expense["original_amount_minor"] == 9007199254740993
            assert expense["exchange_rate_to_cny"] == "0.04876543"
            assert expense["accounting_date"] == "2026-08-31"
            assert "image_path" not in expense and expense["original_reference_id"] == "expense:1:current"
            assert json.loads(package.read("records/goals.jsonl"))["status"] == "archived"
            assert json.loads(package.read("records/expense_revisions.jsonl"))["reason"] == "保留更正"
            assert json.loads(package.read("records/debt_adjustments.jsonl"))["amount_cents"] == -50
            assert [row["state"] for row in observations] == ["verified", "missing"]
            assert package.read(observations[0]["path"]) == source.read_bytes()
            assert observations[0]["sha256"] == digest and observations[1]["path"] is None
            for item in manifest["collections"]:
                content = package.read(item["path"])
                assert hashlib.sha256(content).hexdigest() == item["sha256"]
                assert len(content) == item["size_bytes"] and item["records"] == 1
        request_directory = result.path.parent
    assert not request_directory.exists() and source.is_file()


def test_legacy_and_corrupt_evidence_do_not_block_surviving_business_data(tmp_path, monkeypatch):
    source = _install_files(tmp_path, monkeypatch)
    originals = [_original(1, "available"), _original(2, "available", "0" * 64),
                 _original(3, "available", deleted_at=WHEN), _original(4, None)]
    with portable_export_archive.create_portable_archive(ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=_rows(), originals=iter(originals)) as result, ZipFile(result.path) as package:
        rows = [json.loads(line) for line in package.read("originals.jsonl").splitlines()]
        assert [row["state"] for row in rows] == ["unverified", "corrupt", "cleaned", "none"]
        assert package.read(rows[0]["path"]) == source.read_bytes()
        assert rows[0]["expected_sha256"] is None
        assert all(row["path"] is None for row in rows[1:])
        assert "records/debt_adjustments.jsonl" in package.namelist()
    assert originals[0]["image_hash"] is None


def test_interrupted_record_stream_never_publishes_a_truncated_success(tmp_path, monkeypatch):
    monkeypatch.setattr(portable_export_archive, "TemporaryDirectory", partial(TemporaryDirectory, dir=tmp_path))

    def broken_records():
        yield {"id": 1}
        raise AppError("source_read_failed", status_code=503)

    with pytest.raises(AppError) as caught:
        portable_export_archive.create_portable_archive(ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=[("expenses", broken_records())], originals=iter(()))
    assert caught.value.error == "source_read_failed"
    assert list(tmp_path.iterdir()) == []


def test_export_limit_fails_without_dropping_rows_or_leaving_an_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(portable_export_archive, "TemporaryDirectory", partial(TemporaryDirectory, dir=tmp_path))
    monkeypatch.setattr(portable_export_archive, "MAX_EXPORT_BYTES", 16)
    with pytest.raises(AppError) as caught:
        portable_export_archive.create_portable_archive(ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=_rows(), originals=iter(()))
    assert caught.value.error == "portable_export_limit"
    assert list(tmp_path.iterdir()) == []


def test_cleanup_references_keep_their_identity_without_exposing_storage_paths(tmp_path, monkeypatch):
    source = _install_files(tmp_path, monkeypatch)
    row = _original(1, "uploads/owner/new.png", hashlib.sha256(source.read_bytes()).hexdigest())
    row["attachment_cleanup_request"] = {"request_id": "old-request", "state": "incomplete",
        "image": {"reference": "uploads/owner/old.png", "outcome": "failed", "attempts": 2},
        "thumbnail": {"reference": "uploads/owner/old-thumb.png", "outcome": "deleted", "attempts": 1}}
    with portable_export_archive.create_portable_archive(ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=[("expenses", [row]), ("account_bill_split_inbox", [{"public_id": "inbox"}])],
            originals=[row]) as result, ZipFile(result.path) as package:
        expense = json.loads(package.read("records/expenses.jsonl"))
        cleanup = expense["attachment_cleanup_request"]
        assert cleanup["image"] == {"outcome": "failed", "attempts": 2,
            "reference_id": "expense:1:cleanup:old-request:image"}
        observations = [json.loads(line) for line in package.read("originals.jsonl").splitlines()]
        assert [row["state"] for row in observations] == ["verified", "unverified", "derived_not_included"]
        assert observations[0]["reference_id"] != observations[1]["reference_id"]
        assert observations[0]["path"] == observations[1]["path"]
        assert observations[1]["expected_sha256"] is None
        assert "uploads/owner/" not in package.read("originals.jsonl").decode()
        scope = json.loads(package.read("manifest.json"))["record_scope"]
        assert scope["account_public_id"] == "actor"
        assert scope["account_collections"] == ["account_bill_split_inbox"]
        assert scope["ledger_collections"] == ["expenses"]
    assert row["attachment_cleanup_request"]["image"]["reference"] == "uploads/owner/old.png"


def test_pending_cleanup_of_current_corrupt_original_keeps_the_recorded_identity(tmp_path, monkeypatch):
    _install_files(tmp_path, monkeypatch)
    row = _original(1, "available", "0" * 64)
    row["attachment_cleanup_request"] = {
        "request_id": "cleanup-current",
        "image": {"reference": "available", "outcome": "pending"},
    }
    with portable_export_archive.create_portable_archive(
        ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
        sections=[], originals=[row],
    ) as result, ZipFile(result.path) as package:
        observations = [json.loads(line) for line in package.read("originals.jsonl").splitlines()]
        assert [item["state"] for item in observations] == ["corrupt", "corrupt"]
        assert [item["expected_sha256"] for item in observations] == ["0" * 64, "0" * 64]
        assert not any(name.startswith("originals/") for name in package.namelist())


def test_time_limit_is_checked_after_an_empty_collection_before_the_next_query(monkeypatch):
    monkeypatch.setattr(portable_export_archive, "MAX_EXPORT_SECONDS", -1)

    def must_not_start():
        raise AssertionError("the next query started after the export deadline")
        yield

    with pytest.raises(AppError) as caught:
        portable_export_archive.create_portable_archive(
            ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=[("empty", []), ("later", must_not_start())], originals=[],
        )
    assert caught.value.error == "portable_export_limit"


def test_time_limit_is_checked_after_an_empty_original_query_before_history(monkeypatch):
    monkeypatch.setattr(portable_export_archive, "MAX_EXPORT_SECONDS", -1)

    def must_not_start():
        raise AssertionError("history started after the export deadline")
        yield

    with pytest.raises(AppError) as caught:
        portable_export_archive.create_portable_archive(
            ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=[], originals=[], historical_originals=must_not_start(),
        )
    assert caught.value.error == "portable_export_limit"


def test_original_byte_limit_does_not_masquerade_as_an_unreadable_optional_file(tmp_path, monkeypatch):
    _install_files(tmp_path, monkeypatch)
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    monkeypatch.setattr(portable_export_archive, "TemporaryDirectory", partial(TemporaryDirectory, dir=output_root))
    monkeypatch.setattr(portable_export_archive, "MAX_EXPORT_BYTES", 4)
    with pytest.raises(AppError) as caught:
        portable_export_archive.create_portable_archive(ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=[], originals=[_original(1, "available")])
    assert caught.value.error == "portable_export_limit"
    assert list(output_root.iterdir()) == []


def test_accepted_history_keeps_its_own_original_reference_and_business_text(tmp_path, monkeypatch):
    source = _install_files(tmp_path, monkeypatch)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    receipt = {"id": 4, "resource_type": "expense_offset", "response_body": {"root": {
        "id": 1, "image_path": "uploads/owner/historical.png", "thumbnail_path": "uploads/owner/thumb.png",
        "image_hash": digest, "note": "user wrote C:/notes/tax", "fx_task": {
            "status": "failed", "error_code": "fx_failed", "error_message": "private machine diagnostics"}}}}
    historical = {"accepted_operation_id": 4, "expense_id": 1,
        "image_path": "uploads/owner/historical.png", "image_hash": digest}
    with portable_export_archive.create_portable_archive(ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=[("accepted_operations", [receipt])], originals=[_original(1, "available", digest)],
            historical_originals=[historical]) as result, ZipFile(result.path) as package:
        exported = json.loads(package.read("records/accepted_operations.jsonl"))["response_body"]["root"]
        assert exported["original_reference_id"] == "expense:1:accepted:4"
        assert "image_path" not in exported and "thumbnail_path" not in exported
        assert exported["thumbnail_reference_present"] is True
        assert exported["note"] == "user wrote C:/notes/tax"
        assert exported["fx_task"]["error_code"] == "fx_failed"
        assert "error_message" not in exported["fx_task"]
        index = [json.loads(line) for line in package.read("originals.jsonl").splitlines()]
        assert [row["reference_id"] for row in index] == ["expense:1:current", "expense:1:accepted:4"]
        assert index[0]["path"] == index[1]["path"]
        assert len([name for name in package.namelist() if name.startswith("originals/")]) == 1
    assert receipt["response_body"]["root"]["image_path"] == "uploads/owner/historical.png"


@pytest.mark.parametrize("cleaned_metadata", [{"image_deleted_at": WHEN},
    {"current_image_path": "old", "current_image_deleted_at": WHEN},
    {"attachment_cleanup_request": {"image": {"reference": "old", "outcome": "deleted"}}}])
def test_historical_receipt_does_not_revive_a_known_cleaned_reference(tmp_path, monkeypatch, cleaned_metadata):
    _install_files(tmp_path, monkeypatch)
    history = {"accepted_operation_id": 4, "expense_id": 1, "image_path": "old", **cleaned_metadata}
    with portable_export_archive.create_portable_archive(ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=[], originals=[], historical_originals=[history]) as result, ZipFile(result.path) as package:
        original = json.loads(package.read("originals.jsonl"))
        assert original["state"] == "cleaned" and original["path"] is None
        assert not any(name.startswith("originals/") for name in package.namelist())


def test_identical_original_bytes_with_different_suffixes_share_one_zip_member(tmp_path, monkeypatch):
    first, second = tmp_path / "first.jpg", tmp_path / "second.jpeg"
    first.write_bytes(b"one original image")
    second.write_bytes(first.read_bytes())
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    monkeypatch.setattr(original_read_service, "resolve_protected_image",
        lambda reference, _ledger: (first if reference == "first" else second, "image/jpeg"))
    with portable_export_archive.create_portable_archive(ledger_id="owner", snapshot_at=WHEN, account_public_id="actor",
            sections=[], originals=[_original(1, "first", digest), _original(2, "second", digest)]) as result, \
            ZipFile(result.path) as package:
        rows = [json.loads(line) for line in package.read("originals.jsonl").splitlines()]
        assert rows[0]["reference_id"] != rows[1]["reference_id"]
        assert rows[0]["path"] == rows[1]["path"]
        assert len([name for name in package.namelist() if name.startswith("originals/")]) == 1
