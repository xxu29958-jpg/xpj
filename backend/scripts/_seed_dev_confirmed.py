"""Dev-only helper invoked by seed_dev_confirmed.ps1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database import SessionLocal, init_db
from app.models import Expense
from app.tenants import DEFAULT_TENANT_ID


def main() -> None:
    init_db()
    samples = [
        ("Test Diner", "food", 4580),
        ("Test Store", "life", 1290),
        ("Test Subway", "transit", 800),
    ]
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for i, (merchant, category, amount) in enumerate(samples):
            existing = db.query(Expense).filter(Expense.merchant == merchant).first()
            if existing is not None:
                print(f"skip exists: {merchant}")
                continue
            db.add(
                Expense(
                    tenant_id=DEFAULT_TENANT_ID,
                    amount_cents=amount,
                    merchant=merchant,
                    category=category,
                    note="dev seed",
                    expense_time=now - timedelta(days=i),
                    status="confirmed",
                    image_hash="devseed" + str(i).rjust(3, "0"),
                    file_path="",
                    source="manual",
                )
            )
        db.commit()
    print("SEED_OK")


if __name__ == "__main__":
    main()
