"""Isolated identities, original evidence and read-only package assertions."""

import hashlib
import json
import random
from io import BytesIO
from zipfile import ZipFile

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Expense, ExpenseRevision, Ledger, LedgerMember

LEDGER = "portable-download-ledger"


def seed_identity():
    from app.services.ledger_calendar_service import adopt_ledger_calendar

    with SessionLocal() as db:
        account = Account(display_name="数据下载核对账户")
        db.add(account)
        db.flush()
        db.add(Ledger(ledger_id=LEDGER, name="便携下载核对账本", owner_account_id=account.id))
        db.flush()
        adopt_ledger_calendar(db, ledger_id=LEDGER, timezone_name="Asia/Shanghai", actor_account_id=account.id)
        db.add(LedgerMember(ledger_id=LEDGER, account_id=account.id, role="owner"))
        db.commit()
        return account.id


def pairing_code(account):
    from app.services.identity_service import create_pairing_code

    with SessionLocal() as db:
        return create_pairing_code(db, ledger_id=LEDGER, account_id=account, ttl_minutes=60).pairing_code


def facts():
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.tenant_id == LEDGER))
        if expense is None:
            return {}
        return {"id": expense.id, "public_id": expense.public_id, "amount_cents": expense.amount_cents,
            "fact_revision": expense.fact_revision, "note": expense.note,
            "revisions": len(db.scalars(select(ExpenseRevision).where(ExpenseRevision.expense_id == expense.id)).all())}


def attach_fixture_original(expense_id):
    """Prepare a known historical attachment; financial commands still use the UI."""
    from PIL import Image

    from app.services.currency_binding_service import authorize_currency_metadata_write
    from app.services.file_service import save_upload_bytes

    pixels = random.Random(42).randbytes(1024 * 1024 * 3)
    source = BytesIO()
    Image.frombytes("RGB", (1024, 1024), pixels).save(source, format="PNG")
    content = source.getvalue()
    saved = save_upload_bytes(content, tenant_id=LEDGER, filename="portable-fixture.png", content_type="image/png")
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        expense = db.get(Expense, expense_id)
        expense.image_path, expense.image_hash = saved.relative_path, saved.image_hash
        db.commit()
    return hashlib.sha256(content).hexdigest()


def archive_fixture_ledger(account):
    from app.services.ledger_archive_service import archive_ledger
    from app.services.ledger_service import list_ledgers_for_account

    with SessionLocal() as db:
        assert archive_ledger(db, ledger_id=LEDGER, actor_account_id=account, auth=None)
        assert not list_ledgers_for_account(db, account_id=account), "The owner still has an active ledger"


def verify_package(path, expected, original_digest, *, archived):
    with ZipFile(path) as package:
        assert package.testzip() is None
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["ledger_id"] == LEDGER and manifest["records_complete"] is True
        assert manifest["restore_image"] is False and manifest["includes_client_unsubmitted_intents"] is False
        for collection in manifest["collections"]:
            content = package.read(collection["path"])
            assert hashlib.sha256(content).hexdigest() == collection["sha256"]
            assert len(content) == collection["size_bytes"]
            assert len(content.splitlines()) == collection["records"]
        expenses = [json.loads(line) for line in package.read("records/expenses.jsonl").splitlines()]
        assert len(expenses) == 1 and expenses[0]["id"] == expected["id"]
        assert expenses[0]["amount_cents"] == 12000 and expenses[0]["note"] == "portable-history"
        revisions = [json.loads(line) for line in package.read("records/expense_revisions.jsonl").splitlines()]
        assert len(revisions) == expected["revisions"] and len(revisions) >= 1
        ledgers = [json.loads(line) for line in package.read("records/ledgers.jsonl").splitlines()]
        assert len(ledgers) == 1 and bool(ledgers[0]["archived_at"]) == archived
        index = manifest["originals_index"]
        raw = package.read(index["path"])
        assert hashlib.sha256(raw).hexdigest() == index["sha256"]
        originals = [json.loads(line) for line in raw.splitlines()]
        original = next(row for row in originals if row["reference_id"] == f"expense:{expected['id']}:current")
        assert original["state"] == "verified" and original["sha256"] == original_digest
        assert hashlib.sha256(package.read(original["path"])).hexdigest() == original_digest
        return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
            "collections": len(manifest["collections"]), "expense_revisions": len(revisions),
            "original_sha256": original_digest, "archived": archived}
