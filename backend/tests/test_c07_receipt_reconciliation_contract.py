"""Durable receipt publication and reconciliation contracts for C07."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.database._c07_receipt as c07_receipt
from app.database import _c07_ceremony as c07
from app.services.secure_file import write_protected_file_exclusive

_CEREMONY_ID = "66d65d05-c93a-4fde-b544-5578b6bfa18f"


def test_receipt_publication_never_overwrites_an_existing_artifact(
    tmp_path: Path,
) -> None:
    temporary = tmp_path / ".pending"
    final = tmp_path / "receipt.json"
    write_protected_file_exclusive(temporary, "new receipt\n")
    write_protected_file_exclusive(final, "existing receipt\n")

    with pytest.raises(
        c07.C07ReceiptRepairRequiredError,
        match="publication failed",
    ):
        c07._publish_receipt(  # noqa: SLF001
            temporary,
            final,
            b"new receipt\n",
        )

    assert temporary.read_bytes() == b"new receipt\n"
    assert final.read_bytes() == b"existing receipt\n"


def test_receipt_publication_moves_one_verified_artifact(
    tmp_path: Path,
) -> None:
    temporary = (tmp_path / ".pending").resolve()
    final = (tmp_path / "receipt.json").resolve()
    write_protected_file_exclusive(temporary, "receipt\n")

    c07._publish_receipt(temporary, final, b"receipt\n")  # noqa: SLF001

    assert not temporary.exists()
    assert final.read_bytes() == b"receipt\n"


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (c07._COMMIT_CONFIRMED, "response was lost"),  # noqa: SLF001
        (c07._COMMIT_AMBIGUOUS, "cannot be proven"),  # noqa: SLF001
    ],
)
def test_ambiguous_commit_never_deletes_the_only_repair_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    message: str,
) -> None:
    temporary = tmp_path / ".pending"
    payload = b"durable receipt\n"
    write_protected_file_exclusive(temporary, payload.decode())
    monkeypatch.setattr(
        c07,
        "_classify_staged_receipt_commit",
        lambda *_args, **_kwargs: outcome,
    )

    with pytest.raises(
        c07.C07ReceiptRepairRequiredError,
        match=message,
    ):
        c07._reconcile_staged_receipt_after_transaction_error(  # noqa: SLF001
            SimpleNamespace(),
            ceremony_id=_CEREMONY_ID,
            temporary=temporary,
            receipt_sha256=hashlib.sha256(payload).hexdigest(),
            receipt_payload=payload,
        )

    assert temporary.read_bytes() == payload


def test_commit_recheck_connection_failure_is_ambiguous_and_preserved(
    tmp_path: Path,
) -> None:
    class UnavailableEngine:
        @staticmethod
        def connect():
            raise OSError("injected recheck outage")

    temporary = tmp_path / ".pending"
    payload = b"durable receipt\n"
    write_protected_file_exclusive(temporary, payload.decode())

    with pytest.raises(
        c07.C07ReceiptRepairRequiredError,
        match="cannot be proven",
    ):
        c07._reconcile_staged_receipt_after_transaction_error(  # noqa: SLF001
            UnavailableEngine(),  # type: ignore[arg-type]
            ceremony_id=_CEREMONY_ID,
            temporary=temporary,
            receipt_sha256=hashlib.sha256(payload).hexdigest(),
            receipt_payload=payload,
        )

    assert temporary.read_bytes() == payload


def test_confirmed_rollback_removes_only_its_exact_pending_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = tmp_path / ".pending"
    payload = b"this invocation\n"
    write_protected_file_exclusive(temporary, payload.decode())
    monkeypatch.setattr(
        c07,
        "_classify_staged_receipt_commit",
        lambda *_args, **_kwargs: c07._ROLLBACK_CONFIRMED,  # noqa: SLF001
    )

    c07._reconcile_staged_receipt_after_transaction_error(  # noqa: SLF001
        SimpleNamespace(),
        ceremony_id=_CEREMONY_ID,
        temporary=temporary,
        receipt_sha256=hashlib.sha256(payload).hexdigest(),
        receipt_payload=payload,
    )
    assert not temporary.exists()

    write_protected_file_exclusive(temporary, "conflicting rerun\n")
    with pytest.raises(
        c07.C07ReceiptRepairRequiredError,
        match="conflicts",
    ):
        c07._reconcile_staged_receipt_after_transaction_error(  # noqa: SLF001
            SimpleNamespace(),
            ceremony_id=_CEREMONY_ID,
            temporary=temporary,
            receipt_sha256=hashlib.sha256(payload).hexdigest(),
            receipt_payload=payload,
        )
    assert temporary.read_bytes() == b"conflicting rerun\n"


def test_stage_read_failure_is_reconciled_and_can_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = tmp_path / ".pending"
    state = c07._StagedReceiptState()  # noqa: SLF001
    original_hold = c07_receipt.hold_protected_file_for_read

    def fail_read(_path: Path):
        raise OSError("injected read-after-write failure")

    monkeypatch.setattr(
        c07_receipt,
        "hold_protected_file_for_read",
        fail_read,
    )
    with pytest.raises(c07.C07CeremonyError, match="durably stage"):
        c07._write_receipt_pending(  # noqa: SLF001
            temporary=temporary,
            receipt={"schema": "test-receipt"},
            record_identity=state.record,
        )

    staged = state.value()
    assert staged is not None
    receipt_sha256, receipt_payload = staged
    assert temporary.read_bytes() == receipt_payload

    monkeypatch.setattr(
        c07,
        "_classify_staged_receipt_commit",
        lambda *_args, **_kwargs: c07._ROLLBACK_CONFIRMED,  # noqa: SLF001
    )
    c07._reconcile_staged_receipt_after_transaction_error(  # noqa: SLF001
        SimpleNamespace(),
        ceremony_id=_CEREMONY_ID,
        temporary=temporary,
        receipt_sha256=receipt_sha256,
        receipt_payload=receipt_payload,
    )
    assert not temporary.exists()

    monkeypatch.setattr(
        c07_receipt,
        "hold_protected_file_for_read",
        original_hold,
    )
    retry_state = c07._StagedReceiptState()  # noqa: SLF001
    retry_sha256, retry_payload = c07._write_receipt_pending(  # noqa: SLF001
        temporary=temporary,
        receipt={"schema": "test-receipt"},
        record_identity=retry_state.record,
    )
    assert retry_state.value() == (retry_sha256, retry_payload)
    assert temporary.read_bytes() == retry_payload


def test_ceremony_rerun_never_overwrites_a_conflicting_artifact(
    tmp_path: Path,
) -> None:
    directory = c07.c07_receipt_directory(tmp_path)
    temporary = directory / f".ticketbox-c07-{_CEREMONY_ID}.pending"
    write_protected_file_exclusive(temporary, "earlier attempt\n")

    with pytest.raises(
        c07.C07CeremonyError,
        match="use repair, not overwrite",
    ):
        c07._receipt_paths(_CEREMONY_ID, directory=directory)  # noqa: SLF001

    assert temporary.read_bytes() == b"earlier attempt\n"


def test_disk_budget_requires_dump_scratch_and_twenty_percent_headroom(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        def scalar(self, statement):
            sql = str(statement)
            if "pg_database_size" in sql:
                return 1_000
            if "data_directory" in sql:
                return str(tmp_path)
            raise AssertionError(sql)

    monkeypatch.setattr(
        c07.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=10_000, used=7_599, free=2_401),
    )
    budget = c07._disk_budget(  # noqa: SLF001
        Connection(),
        tmp_path,
        postgres_data_directory=tmp_path,
    )
    assert budget.same_volume is True
    assert budget.backup_required_bytes == 2_400

    monkeypatch.setattr(
        c07.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=10_000, used=7_601, free=2_399),
    )
    with pytest.raises(c07.C07CeremonyError, match="disk preflight refused"):
        c07._disk_budget(  # noqa: SLF001
            Connection(),
            tmp_path,
            postgres_data_directory=tmp_path,
        )
