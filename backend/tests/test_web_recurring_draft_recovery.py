"""Web recurring draft recovery and attempt-at-baseline OCC journeys."""

from __future__ import annotations

import re

import pytest
from _web_recurring_test_support import (
    edit_via_web,
    extract_hidden_token,
    row_version,
    seed_observed_item,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import RecurringItem
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


# 输入类错误的 attempt@baseline: 草稿携带 submitted token, 世界仲裁留给 backend。


def test_web_recurring_edit_input_error_echoes_attempt_baseline_then_occ_arbitrates(
    web_client: TestClient,
) -> None:
    """精确交错回归: GET 时拿到 token7 → 另一消费者推进到 rv8 → 用户仍持 token7
    提交浏览器可达但超出 backend 金额容量的金额 (route 级 parse 失败, 未进
    service/OCC)。错误页必须回声完整草稿
    与原 token7 — 不得把 hidden expected_row_version 升级为 rv8, 否则修正后重提
    会带着从未见过的 baseline 通过 OCC, 静默覆盖远端字段。修正金额后以新 intent
    key 重提 → backend 仲裁判 state_conflict, rv8 不变, 页面只回 server truth。"""
    public_id = seed_observed_item(merchant="房租", occurrence_count=0, source="manual")
    stale_token = row_version(public_id)

    # 另一消费者的合法编辑把条目推进到下一 row_version。
    advanced = edit_via_web(
        web_client,
        public_id,
        merchant="房租",
        amount="7000",
        token=stale_token,
    )
    assert advanced.status_code == 303
    remote_token = row_version(public_id)
    assert remote_token == stale_token + 1

    # 该值通过 type=number/min/step/required，但由 backend MONEY_MINOR_MAX 稳定拒绝。
    # 用户仍持旧 token 时，输入类错误页必须回声完整草稿 + 原 baseline token。
    rejected = edit_via_web(
        web_client,
        public_id,
        merchant="房租（自住）",
        amount="90000000001",
        token=stale_token,
    )
    assert rejected.status_code == 200
    assert "每月金额不是合法金额" in rejected.text
    assert extract_hidden_token(
        rejected.text,
        action=f"/web/recurring/{public_id}/edit",
    ) == str(stale_token)
    form = re.search(
        rf'<details class="rc-edit" open>.*?action="/web/recurring/{re.escape(public_id)}/edit".*?</form>',
        rejected.text,
        re.DOTALL,
    )
    assert form is not None, "input-error render must keep the edit form open with the draft"
    assert 'value="房租（自住）"' in form.group(0)
    assert 'value="90000000001"' in form.group(0)

    # 修正金额、新 intent key 重提: OCC 仲裁 → state_conflict; rv8 原样, 草稿丢弃,
    # 表单回到服务端事实 (merchant 与 token 均为远端当前值)。
    retried = edit_via_web(
        web_client,
        public_id,
        merchant="房租（自住）",
        amount="7200",
        token=stale_token,
    )
    assert retried.status_code == 200
    assert "请核对后再保存" in retried.text
    assert "房租（自住）" not in retried.text
    assert extract_hidden_token(
        retried.text,
        action=f"/web/recurring/{public_id}/edit",
    ) == str(remote_token)
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.row_version == remote_token
        assert item.merchant_name == "房租"
        assert item.baseline_amount_cents == 700_000


def test_web_recurring_edit_input_error_is_correctable_in_place(
    web_client: TestClient,
) -> None:
    """无漂移常态: 浏览器可达的容量错误回声草稿与当前 token, 可就地修正。"""
    public_id = seed_observed_item(occurrence_count=0, source="manual")
    token = row_version(public_id)

    rejected = edit_via_web(
        web_client,
        public_id,
        merchant="物业费",
        amount="90000000001",
        token=token,
    )
    assert rejected.status_code == 200
    assert "每月金额不是合法金额" in rejected.text
    assert extract_hidden_token(
        rejected.text,
        action=f"/web/recurring/{public_id}/edit",
    ) == str(token)
    form = re.search(
        rf'<details class="rc-edit" open>.*?action="/web/recurring/{re.escape(public_id)}/edit".*?</form>',
        rejected.text,
        re.DOTALL,
    )
    assert form is not None
    assert 'value="物业费"' in form.group(0)
    assert 'value="90000000001"' in form.group(0)

    fixed = edit_via_web(
        web_client,
        public_id,
        merchant="物业费",
        amount="300",
        token=token,
    )
    assert fixed.status_code == 303
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.merchant_name == "物业费"
        assert item.baseline_amount_cents == 30_000
        assert item.row_version == token + 1


def test_web_recurring_edit_input_error_yields_to_remote_archive(
    web_client: TestClient,
) -> None:
    """输入错误发生前 target 已被另一消费者归档：页面必须给恢复出口，不能
    伪称旧草稿仍可就地修正，也不能回声旧 OCC token。"""
    public_id = seed_observed_item(merchant="房租", occurrence_count=0, source="manual")
    stale_token = row_version(public_id)

    archived = web_client.post(
        f"/web/recurring/{public_id}/archive",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert archived.status_code == 303

    rejected = edit_via_web(
        web_client,
        public_id,
        merchant="房租（自住）",
        amount="90000000001",
        token=stale_token,
    )

    assert rejected.status_code == 200
    assert "这条固定支出已归档" in rejected.text
    assert "去归档列表恢复" in rejected.text
    assert f'action="/web/recurring/{public_id}/edit"' not in rejected.text
