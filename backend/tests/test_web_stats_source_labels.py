"""/web source labels must match the REAL ``Expense.source`` value domain.

The 2026-06-10 audit found the previous ``SOURCE_LABELS`` key set
(``ios_upload_link``/``android_upload``/``manual``/``web``) had zero overlap
with what the write paths persist (``iPhone截图``/``Android截图``/``手动记账``/
``CSV导入``/``通知草稿:*``/``bill_split_received``) — every /web page showed
未知 and the confirmed-page breakdown collapsed into same-named 其他 rows.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense
from app.services.time_service import now_utc
from app.services.web_stats_service import source_breakdown, source_label


def test_source_label_maps_real_write_path_values() -> None:
    assert source_label("iPhone截图", "未知") == "iPhone"
    assert source_label("Android截图", "未知") == "Android"
    assert source_label("手动记账", "未知") == "手动"
    assert source_label("CSV导入", "未知") == "CSV"
    assert source_label("bill_split_received", "未知") == "拆账"
    # Notification drafts are a prefixed family — every channel maps to 通知.
    assert source_label("通知草稿:微信", "未知") == "通知"
    assert source_label("通知草稿:支付宝", "未知") == "通知"
    # Free-form CSV-supplied sources and blanks fall back per call site.
    assert source_label("自定义来源", "未知") == "未知"
    assert source_label("", "其他") == "其他"
    assert source_label(None, "未知") == "未知"


def _seed_confirmed(source: str, *, count: int) -> None:
    with SessionLocal() as db:
        for _ in range(count):
            db.add(
                Expense(
                    tenant_id="owner",
                    amount_cents=1000,
                    home_currency_code="CNY",
                    original_currency_code="CNY",
                    original_amount_minor=1000,
                    merchant="m",
                    category="餐饮",
                    source=source,
                    status="confirmed",
                    expense_time=now_utc(),
                    confirmed_at=now_utc(),
                )
            )
        db.commit()


def test_source_breakdown_aggregates_after_labeling(client: TestClient) -> None:
    """Distinct stored values sharing one display label (the 通知草稿:*
    channels) must merge into a single row instead of rendering multiple
    identically-named rows."""
    del client  # fixture seeds the schema/identity baseline
    _seed_confirmed("iPhone截图", count=2)
    _seed_confirmed("通知草稿:微信", count=1)
    _seed_confirmed("通知草稿:支付宝", count=1)
    _seed_confirmed("bill_split_received", count=1)

    with SessionLocal() as db:
        rows = source_breakdown(db, "owner", month=None)

    by_label = {row["label"]: row for row in rows}
    assert len(by_label) == len(rows), rows  # no duplicate-label rows
    assert by_label["iPhone"]["count"] == 2
    assert by_label["通知"]["count"] == 2  # 微信 + 支付宝 merged
    assert by_label["拆账"]["count"] == 1
    assert "未知" not in by_label
    assert "其他" not in by_label
