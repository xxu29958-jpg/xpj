"""Web recurring merchant capacity contract and database postconditions."""

from __future__ import annotations

import pytest
from _web_recurring_test_support import (
    create_via_web,
    edit_via_web,
    row_version,
    seed_observed_item,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import RecurringItem
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


# 唯一 Owner 是 backend 的 255 Unicode code-point 合同。HTML maxlength 按
# UTF-16 code units 计数，会静默拦掉合法非 BMP 输入，因此 Web 不设该伪上限。


def test_web_recurring_create_accepts_non_bmp_merchant(web_client: TestClient) -> None:
    """128 个 😀 是合法的 128 code points，必须穿过 Web create 落库。"""
    merchant = "😀" * 128

    created = create_via_web(web_client, merchant=merchant)

    assert created.status_code == 303
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.merchant_name == merchant))
        assert item is not None
        assert item.source == "manual"
        assert len(item.merchant_name) == 128


def test_web_recurring_edit_accepts_non_bmp_merchant_at_code_point_ceiling(
    web_client: TestClient,
) -> None:
    """255 个非 BMP 字符是 255 code points / 510 UTF-16 units，仍合法。"""
    public_id = seed_observed_item(occurrence_count=0, source="manual")
    token = row_version(public_id)
    merchant = "😀" * 255

    edited = edit_via_web(web_client, public_id, merchant=merchant, token=token)

    assert edited.status_code == 303
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.merchant_name == merchant
        assert item.row_version == token + 1


def test_web_recurring_create_over_limit_merchant_surfaces_owner_error(
    web_client: TestClient,
) -> None:
    """>255 code points 由 backend 拒绝，Web 给行动文案且不落行。"""
    rejected = create_via_web(web_client, merchant="😀" * 256)

    assert rejected.status_code == 200
    assert "固定支出名称过长，请缩短后再试。" in rejected.text
    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.tenant_id == "owner")
        )
        assert count == 0


def test_web_recurring_edit_over_limit_merchant_surfaces_owner_error(
    web_client: TestClient,
) -> None:
    """edit 超限同样拒绝，既有行与 OCC token 原样保留。"""
    public_id = seed_observed_item(occurrence_count=0, source="manual")
    token = row_version(public_id)

    rejected = edit_via_web(web_client, public_id, merchant="😀" * 256, token=token)

    assert rejected.status_code == 200
    assert "固定支出名称过长，请缩短后再试。" in rejected.text
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.merchant_name == "Cloud Storage"
        assert item.row_version == token
