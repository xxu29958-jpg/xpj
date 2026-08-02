"""Shared helpers for the /web overview + dashboard-caliber test modules.

照 ``_web_bulk_test_support`` / ``_web_debt_test_support`` 惯例:
跨测试文件共用的播种/造件 helper 收在 ``_*_test_support`` 模块,
两个消费文件都守 500 行债线 (PR #253 R3 拆分)。
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense
from app.services.time_service import current_month, now_utc
from tests._infra.currency import activate_test_currency_authority

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def seed_confirmed_expense(
    client: TestClient, *, identity, amount_cents: int, merchant: str, category: str
) -> None:
    resp = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": category,
            "expense_time": f"{current_month('Asia/Shanghai')}-15T04:00:00Z",
        },
    )
    assert resp.status_code == 200, resp.text


def seed_confirmed_expense_fact(
    *,
    currency_code: str,
    amount_minor: int,
    merchant: str,
    category: str,
) -> None:
    """Seed a historical fact under an already adopted test installation.

    C02 deliberately rejects legacy, unversioned non-CNY writes until C03 adds
    the client contract tuple.  Read/presentation tests still need authentic
    JPY/KRW facts, so they establish persisted authority and insert the frozen
    historical row directly instead of reviving the retired env-authority path.
    """

    with SessionLocal() as db:
        activate_test_currency_authority(db, currency_code)
        recorded_at = datetime.fromisoformat(
            f"{current_month('Asia/Shanghai')}-15T04:00:00+00:00"
        )
        timestamp = now_utc()
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=amount_minor,
                home_currency_code=currency_code,
                original_currency_code=currency_code,
                original_amount_minor=amount_minor,
                exchange_rate_to_cny=Decimal("1"),
                merchant=merchant,
                category=category,
                status="confirmed",
                expense_time=recorded_at,
                confirmed_at=timestamp,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        db.commit()


def create_pending_upload(client: TestClient, *, identity) -> int:
    resp = client.post(
        f"/u/{identity.upload_key}", headers={"Content-Type": "image/png"}, content=TINY_PNG
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def write_fake_dumps(directory: Path) -> tuple[Path, Path]:
    older = directory / "ticketbox-2026-07-01.dump"
    newer = directory / "ticketbox-2026-07-20.dump"
    older.write_bytes(b"not-a-real-dump")
    newer.write_bytes(b"also-not-a-real-dump")
    old_time = time.time() - 86400 * 10
    os.utime(older, (old_time, old_time))
    return older, newer
