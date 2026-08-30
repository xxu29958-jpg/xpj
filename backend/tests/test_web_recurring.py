"""Presentation tests for /web recurring: page render, error surfaces, IA retirements.

Mutation journeys with DB postconditions live in test_web_recurring_commands.py.
"""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from _web_recurring_test_support import (
    create_via_web,
    demote_owner_ledger_to_viewer,
    edit_via_web,
    extract_hidden_token,
    first_recurring_public_id,
    hero_block,
    post_confirm,
    row_version,
    seed_candidate,
    seed_observed_item,
)
from fastapi.testclient import TestClient

from app.main import app
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def test_web_recurring_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/recurring").status_code == 403
    assert client.post("/web/recurring/create").status_code == 403
    assert client.post("/web/recurring/confirm-candidate").status_code == 403
    assert client.post("/web/recurring/x/edit").status_code == 403


def test_web_recurring_create_page_journey(web_client: TestClient) -> None:
    """Writer first-screen CTA + unified form; manual item renders with 每月预计
    honesty (never 上次/最近发生); hero aggregates the active commitment."""
    page = web_client.get("/web/recurring?ledger_id=owner")
    assert page.status_code == 200
    # 主 CTA 首屏可达: 统一创建表单 + durable intent key; 顶栏面包屑消重为页名。
    assert "添加固定支出" in page.text
    assert 'action="/web/recurring/create"' in page.text
    assert re.search(r'name="idempotency_key" value="[^"]+"', page.text)
    assert 'topbar-title">固定支出' in page.text

    assert create_via_web(web_client, merchant="房租", amount="6800", date_str="2026-09-06").status_code == 303

    page = web_client.get("/web/recurring?ledger_id=owner")
    assert "我的固定支出" in page.text
    assert "每月预计" in page.text
    # 诚实合同: manual + occurrence=0 不得出现「上次/最近发生」式观察措辞。
    assert "上次" not in page.text
    # hero 汇总 active 正式项: 每月合计 + 下一笔到期。
    hero = hero_block(page.text)
    assert hero, "active items exist — hero must render"
    assert "6800.00" in hero
    assert "2026-09-06" in hero
    assert "房租" in hero


def test_web_recurring_create_duplicate_active_guides_to_edit(web_client: TestClient) -> None:
    """recurring_item_conflict (active) → 引导编辑且展开碰撞项的编辑表单。"""
    assert create_via_web(web_client, merchant="房租").status_code == 303

    again = create_via_web(web_client, merchant="房租", amount="6900")

    assert again.status_code == 200
    assert "已经在你的固定支出里" in again.text
    assert "去编辑现有记录" in again.text
    assert 'class="rc-edit" open' in again.text


def test_web_recurring_create_duplicate_archived_guides_to_restore(
    web_client: TestClient,
) -> None:
    """recurring_item_conflict (archived) → 引导恢复而非编辑。"""
    assert create_via_web(web_client, merchant="房租").status_code == 303
    public_id = first_recurring_public_id()
    archived = web_client.post(
        f"/web/recurring/{public_id}/archive",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert archived.status_code == 303

    again = create_via_web(web_client, merchant="房租")

    assert again.status_code == 200
    assert "归档" in again.text
    assert "恢复" in again.text


def test_web_recurring_create_rejects_invalid_amount(web_client: TestClient) -> None:
    missing = create_via_web(web_client, amount="")
    assert missing.status_code == 200
    assert "请填写每月金额" in missing.text

    zero = create_via_web(web_client, amount="0")
    assert zero.status_code == 200
    assert "必须大于 0" in zero.text


def test_web_recurring_merchant_inputs_carry_no_browser_length_cap(web_client: TestClient) -> None:
    """HTML maxlength 按 UTF-16 code units 计数 (WHATWG Infra string length):
    任何固定 unit 上限都会在非 BMP 边界误伤合法 code-point 输入 (128 个 😀 =
    128 code points 合法, 却是 256 units)。名称上限的唯一 Owner 是 backend
    (recurring_merchant_too_long), 客户端不设限——本断言杀死原 maxlength="255" 回归。"""
    public_id = seed_observed_item(occurrence_count=0, source="manual")

    page = web_client.get("/web/recurring?ledger_id=owner")

    assert page.status_code == 200
    for input_id in ("rc-add-merchant", f"rc-edit-merchant-{public_id}"):
        tag = re.search(rf'<input\b[^>]*\bid="{re.escape(input_id)}"[^>]*>', page.text)
        assert tag is not None, f"missing merchant input {input_id}"
        assert "maxlength" not in tag.group(0)


def test_web_recurring_over_limit_create_keeps_draft_for_trim_and_resave(
    web_client: TestClient,
) -> None:
    """ERROR_MESSAGE_MAPPING「缩短名称后重新保存; 已填写的其他内容继续保留」的 Web
    落实: 输入类错误保留草稿 (debt_new values / 纠错面 form_values 先例), 用户就地
    修剪名称即可重试, 不必重填金额和日期。"""
    merchant = "😀" * 256

    rejected = create_via_web(web_client, merchant=merchant, amount="6800", date_str="2026-09-06")

    assert rejected.status_code == 200
    assert "固定支出名称过长，请缩短后再试。" in rejected.text
    form = re.search(r'action="/web/recurring/create".*?</form>', rejected.text, re.DOTALL)
    assert form is not None
    assert f'value="{merchant}"' in form.group(0)
    assert 'value="6800"' in form.group(0)
    assert 'value="2026-09-06"' in form.group(0)


def test_web_recurring_over_limit_edit_keeps_draft_and_form_open(web_client: TestClient) -> None:
    """edit 同规则: 草稿回填且该条目编辑表单保持展开; OCC token 仍渲染服务端当前值。"""
    public_id = seed_observed_item(occurrence_count=0, source="manual")
    token = row_version(public_id)
    merchant = "😀" * 256

    rejected = edit_via_web(web_client, public_id, merchant=merchant, amount="25", date_str="2026-10-08", token=token)

    assert rejected.status_code == 200
    assert "固定支出名称过长，请缩短后再试。" in rejected.text
    form = re.search(
        rf'<details class="rc-edit" open>.*?action="/web/recurring/{re.escape(public_id)}/edit".*?</form>',
        rejected.text,
        re.DOTALL,
    )
    assert form is not None, "edit form must stay open with the rejected draft"
    assert f'value="{merchant}"' in form.group(0)
    assert 'value="25"' in form.group(0)
    assert 'value="2026-10-08"' in form.group(0)
    # 草稿回声携带该次 attempt 的 baseline token (attempt@baseline); 本用例无漂移,
    # 故与服务端当前 row_version 同值。
    assert extract_hidden_token(rejected.text, action=f"/web/recurring/{public_id}/edit") == str(token)


def test_web_recurring_conflict_refreshes_instead_of_keeping_draft(web_client: TestClient) -> None:
    """IA 分界的另一半: 世界状态类错误 (冲突/归档/OCC/幂等) 不保留草稿——用户编辑
    针对的是已变化的事实, 页面刷新到服务端真相。"""
    assert create_via_web(web_client, merchant="房租").status_code == 303

    conflict = create_via_web(web_client, merchant="房租", amount="6900")

    assert conflict.status_code == 200
    assert "已经在你的固定支出里" in conflict.text
    form = re.search(r'action="/web/recurring/create".*?</form>', conflict.text, re.DOTALL)
    assert form is not None
    assert 'value="6900"' not in form.group(0)
    merchant_input = re.search(r'<input\b[^>]*\bid="rc-add-merchant"[^>]*>', form.group(0))
    assert merchant_input is not None
    assert 'value=""' in merchant_input.group(0)


def test_web_recurring_edit_stale_row_version_shows_conflict(web_client: TestClient) -> None:
    """OCC: stale token → 诚实冲突文案 + 刷新到最新值。"""
    public_id = seed_observed_item()

    edited = edit_via_web(web_client, public_id, token=row_version(public_id) + 9)

    assert edited.status_code == 200
    assert "请核对后再保存" in edited.text


def test_web_recurring_observed_item_keeps_identity_read_only_but_other_fields_editable(
    web_client: TestClient,
) -> None:
    public_id = seed_observed_item()

    page = web_client.get("/web/recurring?ledger_id=owner")

    assert page.status_code == 200
    form = re.search(
        rf'action="/web/recurring/{re.escape(public_id)}/edit".*?</form>',
        page.text,
        re.DOTALL,
    )
    assert form is not None
    assert 'name="merchant"' in form.group(0)
    assert "readonly" in form.group(0)
    assert "名称与已识别账单绑定" in form.group(0)
    assert 'name="baseline_amount_yuan"' in form.group(0)
    assert 'name="next_expected_date"' in form.group(0)


def test_web_recurring_edit_archived_item_is_rejected(web_client: TestClient) -> None:
    """recurring_item_archived → 诚实呈现, 引导恢复而不是编辑。"""
    public_id = seed_observed_item(status="archived")

    edited = edit_via_web(web_client, public_id, token=row_version(public_id))

    assert edited.status_code == 200
    assert "已归档" in edited.text
    assert "恢复" in edited.text


def test_web_recurring_edit_rename_conflict_guides_to_existing(web_client: TestClient) -> None:
    """edit 改名撞上 recurring_item_conflict: 消费 details, 引导编辑碰撞项。"""
    keep_id = seed_observed_item(
        merchant="房租",
        baseline_cents=680_000,
        last_cents=680_000,
        occurrence_count=0,
        source="manual",
    )
    other_id = seed_observed_item(
        merchant="宽带",
        baseline_cents=10_000,
        last_cents=10_000,
        occurrence_count=0,
        source="manual",
    )

    edited = edit_via_web(web_client, other_id, merchant="房租", amount="100", token=row_version(other_id))

    assert edited.status_code == 200
    assert "已经在你的固定支出里" in edited.text
    assert "去编辑现有记录" in edited.text
    # 链接落点 = 展开碰撞项的编辑表单, 不只是锚定一个关闭的 details。
    form = re.search(
        r'<details class="rc-edit" open>.*?action="/web/recurring/([^"]+)/edit"',
        edited.text,
        re.DOTALL,
    )
    assert form is not None
    assert form.group(1) == keep_id


def test_web_recurring_candidate_confirm_conflict_consumes_details(
    web_client: TestClient,
) -> None:
    """confirm 的 409 消费 details: active/paused 引导编辑现有项 (展开编辑),
    archived 引导归档列表恢复。"""
    assert create_via_web(web_client, merchant="ChatGPT Plus", amount="200", date_str="").status_code == 303
    public_id = first_recurring_public_id()

    conflict = post_confirm(web_client)
    assert conflict.status_code == 200
    assert "已经在你的固定支出里" in conflict.text
    assert "去编辑现有记录" in conflict.text
    form = re.search(
        r'<details class="rc-edit" open>.*?action="/web/recurring/([^"]+)/edit"',
        conflict.text,
        re.DOTALL,
    )
    assert form is not None
    assert form.group(1) == public_id

    archived = web_client.post(
        f"/web/recurring/{public_id}/archive",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert archived.status_code == 303

    conflict = post_confirm(web_client)
    assert conflict.status_code == 200
    assert "已归档" in conflict.text
    assert "去归档列表恢复" in conflict.text


@pytest.mark.parametrize(
    ("merchant", "message"),
    [
        ("   ", "请填写固定支出的商家或名称。"),
        ("😀" * 256, "固定支出名称过长，请缩短后再试。"),
    ],
)
def test_web_recurring_candidate_confirm_surfaces_stable_merchant_errors(
    web_client: TestClient,
    merchant: str,
    message: str,
) -> None:
    rejected = post_confirm(web_client, merchant=merchant)

    assert rejected.status_code == 200
    assert message in rejected.text


def test_web_recurring_hero_sums_active_items_only_and_ignores_filter(
    web_client: TestClient,
) -> None:
    """hero 只汇总 active, 且不随列表状态筛选漂移。"""
    assert create_via_web(web_client, merchant="房租", amount="6000", date_str="2026-09-05").status_code == 303
    assert create_via_web(web_client, merchant="宽带", amount="100", date_str="2026-09-01").status_code == 303
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import RecurringItem

    with SessionLocal() as db:
        paused_id = db.scalar(
            select(RecurringItem.public_id).where(RecurringItem.merchant_name == "宽带")
        )
    assert paused_id is not None
    paused = web_client.post(
        f"/web/recurring/{paused_id}/pause",
        data={"ledger_id": "owner", "expected_row_version": row_version(paused_id)},
        follow_redirects=False,
    )
    assert paused.status_code == 303

    for suffix in ("", "&status=paused", "&status=archived"):
        page = web_client.get(f"/web/recurring?ledger_id=owner{suffix}")
        hero = hero_block(page.text)
        assert hero, f"hero must not drift with filter {suffix!r}"
        assert "6000.00" in hero
        assert "6100.00" not in hero
        assert "2026-09-05" in hero
        assert "2026-09-01" not in hero


def test_web_recurring_candidate_review_form_shows_server_provenance(
    web_client: TestClient,
) -> None:
    """复核页展示服务端候选观察, 但表单只回传 merchant + amount 定位:
    不再携带 occurrence_count / last_seen_at / confidence 隐藏字段。"""
    seed_candidate()

    page = web_client.get("/web/recurring?ledger_id=owner&review=ChatGPT+Plus")

    assert page.status_code == 200
    assert 'action="/web/recurring/confirm-candidate"' in page.text
    assert "已观察 3 次" in page.text
    assert 'value="ChatGPT Plus"' in page.text
    assert 'name="amount_cents" value="20000"' in page.text
    assert 'name="occurrence_count"' not in page.text
    assert 'name="last_seen_at"' not in page.text
    assert 'name="confidence"' not in page.text


def test_web_recurring_candidate_insight_failure_degrades(
    web_client: TestClient,
    monkeypatch,
) -> None:
    # Coverage migrated from the deleted /web/stats page: the candidate
    # insight blowing up must degrade to an inline notice, never 500.
    from app.routes import web_recurring as web_recurring_module

    def fail_recurring_candidates(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(web_recurring_module, "recurring_candidates", fail_recurring_candidates)

    resp = web_client.get("/web/recurring?ledger_id=owner")

    assert resp.status_code == 200
    assert "固定支出候选分析暂时不可用" in resp.text
    # 候选失败不压过主任务: 主列表与创建表单仍在。
    assert "我的固定支出" in resp.text
    assert 'action="/web/recurring/create"' in resp.text


def test_web_recurring_viewer_read_only(web_client: TestClient) -> None:
    seed_candidate()
    demote_owner_ledger_to_viewer()

    page = web_client.get("/web/recurring?ledger_id=owner")
    assert page.status_code == 200
    assert "只读角色" in page.text
    # viewer: 创建/复核/编辑/状态动作全部隐藏。
    assert 'action="/web/recurring/create"' not in page.text
    assert 'action="/web/recurring/confirm-candidate"' not in page.text
    assert "复核采用" not in page.text
    assert 'class="rc-edit"' not in page.text
    assert 'name="expected_row_version"' not in page.text

    denied = web_client.post(
        "/web/recurring/create",
        data={
            "ledger_id": "owner",
            "merchant": "房租",
            "baseline_amount_yuan": "6800",
            "next_expected_date": "2026-09-06",
            "idempotency_key": str(uuid4()),
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"] == "permission_denied"

    denied_confirm = post_confirm(web_client)
    assert denied_confirm.status_code == 403
    assert denied_confirm.json()["error"] == "permission_denied"


def test_web_recurring_retires_legacy_candidate_only_surface(web_client: TestClient) -> None:
    """物理退役: 7 列 dt-table / 恒定周期列 / 无异常「正常」噪声 / 行内一键确认。"""
    seed_candidate()
    assert create_via_web(web_client, merchant="房租").status_code == 303

    page = web_client.get("/web/recurring?ledger_id=owner")

    assert page.status_code == 200
    assert 'class="dt-table"' not in page.text
    assert "<th>周期</th>" not in page.text
    assert ">正常</span>" not in page.text
    assert "固定支出候选（未确认）" not in page.text
    assert "待确认候选" not in page.text
    # 候选动作 = 进入统一表单的复核链接; 默认页不再渲染任何确认表单。
    assert "复核采用" in page.text
    assert 'action="/web/recurring/confirm-candidate"' not in page.text
    assert "填入创建表单" not in page.text
