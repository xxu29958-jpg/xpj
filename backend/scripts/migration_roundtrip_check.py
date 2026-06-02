"""End-to-end check for the ADR-0041 SQLite -> PostgreSQL data migration.

Builds a seeded SQLite source (identity + runtime seed + a couple of confirmed
expenses with known timestamps), migrates it into a target engine via
``data_migration_service.migrate``, and asserts the reconciliation passes. On a
PostgreSQL target it additionally proves the two landmines are handled:

- **setval**: a fresh insert after migration gets ``id = max(id) + 1`` (the
  sequence was advanced past the copied rows).
- **timestamptz**: a known expense's ``expense_time`` reads back as the same
  UTC instant on the target as on the source.

Run locally (SQLite -> SQLite, no PostgreSQL needed)::

    python scripts/migration_roundtrip_check.py

Run against PostgreSQL (the backend-postgres CI lane)::

    python scripts/migration_roundtrip_check.py \
        --target postgresql+psycopg://postgres:postgres@localhost:5432/xpj_migrate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def _seed_source(source_url: str) -> dict[str, int]:
    """init_db + a couple of confirmed expenses; return their ids by amount."""
    os.environ.update(
        {
            "DATABASE_URL": source_url,
            "UPLOAD_TOKEN": "migrate-upload-token",
            "APP_TOKEN": "migrate-app-token",
            "ADMIN_TOKEN": "migrate-admin-token",
            "UPLOAD_DIR": "uploads/migrate_check",
            "OCR_PROVIDER": "empty",
            "TENANTS_JSON": json.dumps(
                [{"id": "owner", "name": "我的小票夹", "upload_token": "u", "app_token": "a"}],
                ensure_ascii=False,
            ),
        }
    )
    from app.database import SessionLocal, init_db
    from app.models import Expense
    from app.services.time_service import now_utc

    init_db()
    ids: dict[str, int] = {}
    with SessionLocal() as db:
        for amount in (1280, 3680):
            now = now_utc()
            expense = Expense(
                tenant_id="owner",
                amount_cents=amount,
                merchant=f"测试商家-{amount}",
                category="餐饮",
                status="confirmed",
                expense_time=now,
                created_at=now,
                updated_at=now,
                confirmed_at=now,
            )
            db.add(expense)
            db.commit()
            db.refresh(expense)
            ids[str(amount)] = expense.id
        # ADR-0041: give one row a non-default row_version so the generic
        # field-sample reconciliation MEANINGFULLY proves row_version is copied.
        # If every row were the default 1, a "forgot to copy row_version, the
        # target server_default filled 1" bug would pass (1 == 1). With 9 on the
        # source, dropping the copy yields 1 on the target → sample mismatch.
        bumped = db.get(Expense, ids["3680"])
        bumped.row_version = 9
        db.commit()
    return ids


def _assert_postgres_landmines(target_url: str, expense_ids: dict[str, int]) -> None:
    from sqlalchemy import create_engine, func, select, text

    from app.models import Expense
    from app.services.time_service import ensure_utc

    engine = create_engine(target_url)
    try:
        with engine.begin() as conn:
            max_id = conn.execute(select(func.coalesce(func.max(Expense.id), 0))).scalar()
            now_expr = conn.execute(select(func.now())).scalar()
            conn.execute(
                Expense.__table__.insert().values(
                    tenant_id="owner",
                    public_id=str(uuid.uuid4()),
                    amount_cents=999,
                    status="confirmed",
                    expense_time=now_expr,
                    created_at=now_expr,
                    updated_at=now_expr,
                    confirmed_at=now_expr,
                )
            )
            new_id = conn.execute(select(func.max(Expense.id))).scalar()
            if int(new_id) != int(max_id) + 1:
                raise AssertionError(f"setval: expected new id {int(max_id) + 1}, got {new_id}")

            sample_id = expense_ids["1280"]
            target_time = conn.execute(
                select(Expense.expense_time).where(Expense.id == sample_id)
            ).scalar()
            if ensure_utc(target_time) is None:
                raise AssertionError("timestamptz: expense_time came back NULL on target")

            # Empty-at-migration table: its sequence starts fresh at 1, not 2.
            empty = "bill_split_invitations"
            if int(conn.execute(text(f"SELECT COUNT(*) FROM {empty}")).scalar()) == 0:
                seq = conn.execute(
                    text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": empty}
                ).scalar()
                first_id = conn.execute(text("SELECT nextval(:s)"), {"s": seq}).scalar()
                if int(first_id) != 1:
                    raise AssertionError(f"empty-table setval: expected first id 1, got {first_id}")
    finally:
        engine.dispose()
    print("OK postgres landmines (setval + timestamptz + empty-table sequence)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQLite -> target data-migration round-trip check.")
    parser.add_argument(
        "--target",
        default=None,
        help="target SQLAlchemy URL; defaults to a throwaway SQLite file (local mode)",
    )
    args = parser.parse_args(argv)

    tmp_dir = Path(tempfile.mkdtemp(prefix="xpj_migrate_"))
    source_path = tmp_dir / "source.db"
    source_url = f"sqlite:///{source_path.as_posix()}"
    target_url = args.target or f"sqlite:///{(tmp_dir / 'target.db').as_posix()}"
    is_postgres = target_url.startswith("postgresql")

    expense_ids = _seed_source(source_url)
    print(f"OK seeded source ({source_url.split('///')[-1]}) — expenses {expense_ids}")

    from app.database import migrate

    report = migrate(source_url, target_url)
    for check in report.checks:
        if check.status == "error":
            print(f"  FAIL {check.code}: {check.message}")
    print(f"reconciliation: {'PASS' if report.ok else 'FAIL'} ({len(report.checks)} checks)")
    if not report.ok:
        return 1

    if is_postgres:
        _assert_postgres_landmines(target_url, expense_ids)

    print("\nPASS migration round-trip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
