"""Read real task/expense postconditions; seed only isolated access changes."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager


def facts(ledger_id):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import BackgroundTask, Expense
    from app.services.original_read_service import read_original_snapshot

    with SessionLocal() as db:
        expenses = []
        for expense in db.scalars(select(Expense).where(Expense.tenant_id == ledger_id).order_by(Expense.id)):
            with read_original_snapshot(relative_path=expense.image_path, tenant_id=ledger_id,
                                        expected_sha256=expense.image_hash) as original:
                digest = hashlib.sha256(original.path.read_bytes()).hexdigest()
            expenses.append({"id": expense.id, "amount": expense.amount_cents,
                "merchant": expense.merchant, "status": expense.status,
                "version": expense.row_version, "fact_revision": expense.fact_revision,
                "original_currency": expense.original_currency_code,
                "original_amount": expense.original_amount_minor, "home_currency": expense.home_currency_code,
                "fx_status": expense.fx_status, "rate": str(expense.fx_rate) if expense.fx_rate else None,
                "rate_date": expense.fx_rate_date.isoformat() if expense.fx_rate_date else None,
                "note": expense.note, "original_sha256": digest,
                "expense_time": expense.expense_time.isoformat() if expense.expense_time else None})
        tasks = [{"id": task.public_id, "type": task.task_type, "status": task.status,
                  "expense_id": task.source_expense_id,
                  "result": json.loads(task.result_summary_json) if task.result_summary_json else None,
                  "error_code": task.error_code}
                 for task in db.scalars(select(BackgroundTask).where(
                     BackgroundTask.tenant_id == ledger_id).order_by(BackgroundTask.id))]
        return {"expenses": expenses, "tasks": tasks}


@contextmanager
def denied_membership(ledger_id):
    """Simulate external revocation of fixture identity, never a business write."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Ledger, LedgerMember
    from app.services.time_service import now_utc

    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id))
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == ledger_id,
            LedgerMember.account_id == ledger.owner_account_id))
        assert member is not None and member.disabled_at is None
        member_id = member.id
        member.disabled_at = now_utc()
        db.commit()
    try:
        yield
    finally:
        with SessionLocal() as db:
            db.get(LedgerMember, member_id).disabled_at = None
            db.commit()


def synthetic_receipt(path, *, amount="18.51", date_text="2026年9月28日"):
    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("RGB", (1050, 640), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 38)
    for index, line in enumerate(("合成测试小票（非真实凭证）", "星河便利店",
                                 f"交易时间：{date_text} 12:34:56", "商品：饮用水",
                                 f"交易金额：{amount}（人民币）", "仅用于隔离验证")):
        draw.text((45, 35 + index * 95), line, fill="black", font=font)
    canvas.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()
