"""/web/repayment-drafts 还款捕获复核页 (ADR-0049 债务域 web 面 slice C3).

列表 = account-scoped 隐私 (只列 viewer 自己创建的捕获) × 选定账本作用域 (每行可操作，
确认走选定账本的可写权限与该账本候选债的 OCC 快照；跨账本捕获不进列表)。pending → 逐项
确认表单组 (每个候选债一个表单，各带自己的 target_debt_public_id + expected_row_version
隐藏字段——OCC 快照随目标走，无 JS 也提交不错版本；服务端建议项给徽标与主按钮层级)，
每行每渲染一套幂等键；confirmed → 已记账 + 关联债；dismissed → 已忽略 沉降。视觉为
新设计系统语言 (product-*)，不断言任何 main 旧视觉类。

uses ``web_client`` (conftest) 绕过 /web loopback 门(同 test_web_debts);plain ``client``
留门给 remote-403。本文件自包含 seed(经 /api 建草稿/债务 + ORM 直接 seed 成员/二账本),
拆独立文件守 files_over_500(test_web_debts.py 已逼近 500)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, LedgerMember
from app.routes import web_repayment_drafts as web_repayment_drafts_module
from app.routes.web_common import LedgerOption
from app.routes.web_repayment_drafts import _audit_row_view
from app.services.debt_service import RepaymentDraftAuditRow
from app.services.debt_service._repayment_draft_match import RepaymentMatchCandidate
from app.services.identity_service import hash_secret, new_session_token


# ── /api seeding helpers ─────────────────────────────────────────────────────
def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _create_draft(
    web_client: TestClient,
    headers: dict[str, str],
    *,
    source: str = "alipay",
    amount_cents: int = 20000,
    merchant_label: str | None = "花呗",
) -> dict:
    body: dict[str, object] = {"source": source, "amount_cents": amount_cents}
    if merchant_label is not None:
        body["merchant_label"] = merchant_label
    resp = web_client.post("/api/repayment-drafts", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_debt(
    web_client: TestClient,
    headers: dict[str, str],
    *,
    label: str | None = "招商信用卡",
    principal_cents: int = 50000,
) -> dict:
    body: dict[str, object] = {
        "direction": "i_owe",
        "counterparty_type": "external",
        "principal_amount_cents": principal_cents,
    }
    if label is not None:
        body["counterparty_label"] = label
    resp = web_client.post("/api/debts", headers=_idem(headers), json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _confirm_via_api(web_client: TestClient, headers: dict[str, str], draft: dict, debt: dict) -> None:
    resp = web_client.post(
        f"/api/repayment-drafts/{draft['public_id']}/confirm",
        headers=_idem(headers),
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]},
    )
    assert resp.status_code == 201, resp.text


def _dismiss_via_api(web_client: TestClient, headers: dict[str, str], draft: dict) -> None:
    resp = web_client.post(f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=headers, json={})
    assert resp.status_code == 201, resp.text


def _seed_member_token(*, name: str, ledger_id: str = "owner") -> dict[str, str]:
    """Add a writer MEMBER account to a ledger and mint its app token (a SECOND
    capturer in the same ledger — the account-isolation foil)."""
    with SessionLocal() as db:
        account = Account(display_name=name)
        db.add(account)
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role="member"))
        device = Device(account_id=account.id, device_name="pytest-rd-web", platform="android")
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account.id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
            )
        )
        db.commit()
        return {"Authorization": f"Bearer {token}"}


def _page(web_client: TestClient) -> str:
    resp = web_client.get("/web/repayment-drafts?ledger_id=owner")
    assert resp.status_code == 200, resp.text
    return resp.text


def _viewer_role(monkeypatch) -> None:
    """Force the selected ledger option to role=viewer (只读角色路径)。"""
    monkeypatch.setattr(
        web_repayment_drafts_module,
        "_list_ledger_options",
        lambda _db: [
            LedgerOption(
                ledger_id="owner",
                name="家庭账本",
                role="viewer",
                is_default=True,
                pending_count=0,
                confirmed_count=0,
            )
        ],
    )


def _web_confirm(
    web_client: TestClient,
    *,
    draft: dict,
    debt: dict,
    idempotency_key: str | None = None,
    row_version: int | str | None = None,
):
    return web_client.post(
        f"/web/repayment-drafts/{draft['public_id']}/confirm",
        data={
            "ledger_id": "owner",
            "target_debt_public_id": debt["public_id"],
            "expected_row_version": str(debt["row_version"] if row_version is None else row_version),
            "idempotency_key": idempotency_key or str(uuid4()),
            "csrf_token": "test-client-bypasses-middleware-check",
        },
        follow_redirects=False,
    )


def _web_dismiss(web_client: TestClient, *, draft: dict):
    return web_client.post(
        f"/web/repayment-drafts/{draft['public_id']}/dismiss",
        data={
            "ledger_id": "owner",
            "csrf_token": "test-client-bypasses-middleware-check",
        },
        follow_redirects=False,
    )


def _drafts_via_api(web_client: TestClient, headers: dict[str, str], status: str) -> list[dict]:
    return web_client.get(f"/api/repayment-drafts?status={status}", headers=headers).json()["items"]


# ── gate + empty ─────────────────────────────────────────────────────────────
def test_web_repayment_drafts_remote_returns_403(client: TestClient) -> None:
    # No loopback / no session override → the LocalOnly gate must 403.
    assert client.get("/web/repayment-drafts").status_code == 403


def test_web_repayment_drafts_empty_renders_product_empty_state(web_client: TestClient) -> None:
    html = _page(web_client)
    assert "还没有还款捕获" in html
    assert "product-state" in html  # 新设计系统空态 (非 main 的 dt-card--empty)
    assert "确认记到哪笔欠款也在这一页完成" in html


def test_page_header_uses_product_eyebrow(web_client: TestClient) -> None:
    html = _page(web_client)
    assert "product-eyebrow" in html
    assert "往来 / 还款捕获" in html
    assert "product-page-summary" in html


# ── pending row + actionable per-choice forms + suggested provenance ─────────
def test_pending_draft_renders_audit_row(web_client: TestClient, *, identity) -> None:
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    assert "待复核" in html
    assert "支付宝还款" in html  # source label mirrors Android (alipay → 支付宝还款, §14)
    assert "花呗" in html  # merchant
    assert "¥200.00" in html  # amount (home-currency, 20000 cents)


def test_pending_with_matching_debt_renders_per_choice_form(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(web_client, identity.app_headers, label="花呗", principal_cents=50000)
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    # 建议保持中性 provenance (建议是建议不是事实)，建议项在表单组里拿徽标+主按钮。
    assert "系统猜测对应:花呗" in html
    assert "ra-badge" in html
    # 逐项表单：OCC 快照随该候选自己的隐藏字段走 (无 JS 也提交不错版本)。
    assert f'name="target_debt_public_id" value="{debt["public_id"]}"' in html
    assert f'name="expected_row_version" value="{debt["row_version"]}"' in html
    assert "花呗 · 剩余 ¥500.00" in html
    assert 'name="idempotency_key"' in html  # 每行每渲染一套幂等键
    assert 'name="csrf_token"' in html
    assert "确认" in html
    assert ">忽略</button>" in html
    # 审计表头 (新设计系统的四列网格)。
    assert "repayment-audit-head" in html


def test_pending_without_match_shows_no_provenance(web_client: TestClient, *, identity) -> None:
    # No repayable Debt at all → no confident suggestion → no provenance line.
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    assert "待复核" in html
    assert "系统猜测对应" not in html


def test_pending_picker_excludes_a_debt_that_cannot_cover_the_draft(web_client: TestClient, *, identity) -> None:
    # Feasibility: a Debt whose folded remaining can't cover the draft amount is not a
    # target (would only fail as overpayment at confirm time).
    _create_debt(web_client, identity.app_headers, label="额度不足的欠款", principal_cents=5000)
    _create_draft(web_client, identity.app_headers, merchant_label="额度不足的欠款", amount_cents=10000)
    html = _page(web_client)
    assert "额度不足的欠款 · 剩余" not in html
    # 诚实空目标态：不给死表单，给去建欠款的真实行动 + 保留忽略出口。
    assert "当前账本没有可对应的欠款" in html
    assert 'href="/web/debts?ledger_id=owner"' in html
    assert ">忽略</button>" in html


# ── confirm: idempotent + OCC ────────────────────────────────────────────────
def test_confirm_is_occ_backed_and_idempotent(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(web_client, identity.app_headers, label="招商信用卡", principal_cents=50000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="信用卡", amount_cents=10000)
    key = str(uuid4())

    first = _web_confirm(web_client, draft=draft, debt=debt, idempotency_key=key)
    replay = _web_confirm(web_client, draft=draft, debt=debt, idempotency_key=key)

    assert first.status_code == 303
    assert replay.status_code == 303  # 重放返回 canonical 结果，不再记第二笔
    confirmed = _drafts_via_api(web_client, identity.app_headers, "confirmed")
    assert [item["public_id"] for item in confirmed] == [draft["public_id"]]
    current = web_client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert current.status_code == 200, current.text
    assert current.json()["remaining_amount_cents"] == 40000


def test_confirm_malformed_token_rerenders_422_anchored_and_marks_attempted(
    web_client: TestClient, *, identity
) -> None:
    debt = _create_debt(web_client, identity.app_headers, label="花呗-可选欠款", principal_cents=50000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="花呗-保留行", amount_cents=10000)

    response = _web_confirm(web_client, draft=draft, debt=debt, row_version="stale-token")

    assert response.status_code == 422
    assert "欠款信息已经失效，请刷新后重新选择。" in response.text
    assert "花呗-保留行" in response.text  # 原地重渲染：捕获行还在
    assert 'role="alert"' in response.text  # 错误锚定到该 row (aria)
    assert "（刚才选择）" in response.text  # 尝试过的选项被回填标记，不靠用户猜
    assert 'name="idempotency_key"' in response.text  # 表单立即可重试
    assert [item["public_id"] for item in _drafts_via_api(web_client, identity.app_headers, "pending")] == [
        draft["public_id"]
    ]


def test_confirm_stale_row_version_redirects_with_error_and_stays_pending(
    web_client: TestClient, *, identity
) -> None:
    # Well-formed but OUTDATED OCC snapshot: another repayment bumps the Debt's
    # row_version after the page was rendered → service state_conflict (409) →
    # redirect with a human error, draft stays pending, no double-write.
    debt = _create_debt(web_client, identity.app_headers, label="招商信用卡", principal_cents=50000)
    stale_version = debt["row_version"]
    draft = _create_draft(web_client, identity.app_headers, merchant_label="信用卡", amount_cents=10000)
    other = _create_draft(web_client, identity.app_headers, merchant_label="另一笔", amount_cents=5000)
    _confirm_via_api(web_client, identity.app_headers, other, debt)  # bumps row_version

    response = _web_confirm(web_client, draft=draft, debt=debt, row_version=stale_version)

    assert response.status_code == 303
    assert "form_error=" in response.headers["location"]
    assert [item["public_id"] for item in _drafts_via_api(web_client, identity.app_headers, "pending")] == [
        draft["public_id"]
    ]
    # The first repayment is untouched (exactly one confirmed).
    assert len(_drafts_via_api(web_client, identity.app_headers, "confirmed")) == 1


def test_confirm_without_idempotency_key_rerenders_422(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(web_client, identity.app_headers, principal_cents=50000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="缺键", amount_cents=10000)
    resp = web_client.post(
        f"/web/repayment-drafts/{draft['public_id']}/confirm",
        data={
            "ledger_id": "owner",
            "target_debt_public_id": debt["public_id"],
            "expected_row_version": str(debt["row_version"]),
            "idempotency_key": "",
            "csrf_token": "test-client-bypasses-middleware-check",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert "页面凭据缺失，请刷新后重新提交。" in resp.text
    assert [item["public_id"] for item in _drafts_via_api(web_client, identity.app_headers, "pending")] == [
        draft["public_id"]
    ]


def test_confirm_cannot_resolve_another_accounts_capture(web_client: TestClient, *, identity) -> None:
    member = _seed_member_token(name="另一位家人")
    member_draft = _create_draft(web_client, member, merchant_label="另一位家人的花呗", amount_cents=10000)
    owner_debt = _create_debt(web_client, identity.app_headers, label="我的花呗", principal_cents=50000)

    response = _web_confirm(web_client, draft=member_draft, debt=owner_debt)

    assert response.status_code == 303
    assert "form_error=" in response.headers["location"]
    assert [item["public_id"] for item in _drafts_via_api(web_client, member, "pending")] == [
        member_draft["public_id"]
    ]


def test_selected_ledger_action_cannot_resolve_another_ledgers_draft(
    web_client: TestClient, *, identity
) -> None:
    other_draft = _create_draft(web_client, identity.gray_app_headers, merchant_label="二账本草稿", amount_cents=10000)
    owner_debt = _create_debt(web_client, identity.app_headers, label="本账本欠款", principal_cents=50000)

    response = _web_confirm(web_client, draft=other_draft, debt=owner_debt)

    assert response.status_code == 303
    assert "form_error=" in response.headers["location"]
    assert [item["public_id"] for item in _drafts_via_api(web_client, identity.gray_app_headers, "pending")] == [
        other_draft["public_id"]
    ]


def test_selected_ledger_viewer_cannot_confirm(web_client: TestClient, *, identity, monkeypatch) -> None:
    debt = _create_debt(web_client, identity.app_headers)
    draft = _create_draft(web_client, identity.app_headers)
    _viewer_role(monkeypatch)

    response = _web_confirm(web_client, draft=draft, debt=debt)

    assert response.status_code == 403
    assert [item["public_id"] for item in _drafts_via_api(web_client, identity.app_headers, "pending")] == [
        draft["public_id"]
    ]


def test_viewer_never_sees_the_action_form(web_client: TestClient, *, identity, monkeypatch) -> None:
    # 不可用功能不得伪装为可用：viewer 的行没有表单，行内诚实提示 + 顶部只读说明。
    _create_debt(web_client, identity.app_headers, label="花呗", principal_cents=50000)
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=10000)
    _viewer_role(monkeypatch)
    html = _page(web_client)
    assert "只读角色可以查看还款捕获" in html
    assert "等待有写权限的成员处理" in html
    assert 'name="target_debt_public_id"' not in html
    assert "确认" not in html.split("等待有写权限的成员处理")[0].split("repayment-audit-row")[-1]


# ── dismiss: replay-safe terminal flip ───────────────────────────────────────
def test_dismiss_is_repeat_safe_and_stays_in_audit_history(web_client: TestClient, *, identity) -> None:
    draft = _create_draft(web_client, identity.app_headers, merchant_label="白条-忽略", amount_cents=8000)

    first = _web_dismiss(web_client, draft=draft)
    replay = _web_dismiss(web_client, draft=draft)
    html = _page(web_client)

    assert first.status_code == 303
    assert replay.status_code == 303  # 终态翻转幂等：重复忽略不报错
    assert "白条-忽略" in html
    assert "已忽略" in html
    assert "is-receded" in html


# ── confirmed (linked debt) / dismissed (sunk) rendering ─────────────────────
def test_confirmed_draft_shows_linked_debt(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(web_client, identity.app_headers, label="招商信用卡", principal_cents=50000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="信用卡", amount_cents=10000)
    _confirm_via_api(web_client, identity.app_headers, draft, debt)
    html = _page(web_client)
    assert "已记账" in html
    assert "已记到:招商信用卡" in html
    # A resolved draft never carries the ephemeral suggestion provenance nor an action form.
    assert "系统猜测对应" not in html
    assert 'name="target_debt_public_id"' not in html


# (No fallback-name test: 外部债建账强制非空 counterparty_label〔422 without〕 and confirm only
# targets external/manual Debt, so a referenced Debt always has a label — the route's 外部欠款
# fallback is defensive-only, an unconstructable state, so there is nothing real to pin.)


def test_dismissed_draft_receded_and_ignored_label(web_client: TestClient, *, identity) -> None:
    draft = _create_draft(web_client, identity.app_headers, merchant_label="白条", amount_cents=8000)
    _dismiss_via_api(web_client, identity.app_headers, draft)
    html = _page(web_client)
    assert "已忽略" in html
    assert "is-receded" in html  # dismissed rows recede (永不红)


# ── account privacy × selected-ledger scope ──────────────────────────────────
def test_account_scoped_hides_other_members_captures(web_client: TestClient, *, identity) -> None:
    # Owner's own capture shows; a SECOND member's capture in the SAME ledger must NOT
    # (account-scoped, not ledger-scoped — repayment notifications are private).
    _create_draft(web_client, identity.app_headers, merchant_label="花呗-我的", amount_cents=10000)
    member = _seed_member_token(name="家人")
    _create_draft(web_client, member, merchant_label="借呗-家人的", amount_cents=9000)
    html = _page(web_client)
    assert "花呗-我的" in html  # viewer (owner) sees own capture
    assert "借呗-家人的" not in html  # member's private capture hidden from the owner's view


def test_cross_ledger_captures_do_not_leak_into_selected_ledger(web_client: TestClient, *, identity) -> None:
    # 可操作化后列表与动作同域：二账本捕获不进 owner 账本视图 (旧只读审计曾跨账本聚合，
    # 但可操作的跨账本行只会提交必错——服务侧按 tenant 锁草稿)。
    _create_draft(web_client, identity.app_headers, merchant_label="花呗-本账本", amount_cents=10000)
    _create_debt(web_client, identity.gray_app_headers, label="工行信用卡", principal_cents=50000)
    _create_draft(web_client, identity.gray_app_headers, merchant_label="信用卡-二账本", amount_cents=10000)
    html = _page(web_client)
    assert "花呗-本账本" in html
    assert "信用卡-二账本" not in html
    assert "工行信用卡" not in html


def test_newest_first_ordering(web_client: TestClient, *, identity) -> None:
    _create_draft(web_client, identity.app_headers, merchant_label="先记的", amount_cents=10000)
    _create_draft(web_client, identity.app_headers, merchant_label="后记的", amount_cents=11000)
    html = _page(web_client)
    assert html.index("后记的") < html.index("先记的")  # newest-first


# ── _audit_row_view pure unit (tones + per-choice flags + prefixes + 防御 fallback) ──
# Pin the view dict directly: the HTTP tests check rendered HTML substrings, but not the
# pill TONE, the per-choice is_suggested/is_selected flags, or the defensive 外部欠款
# fallback (an unconstructable null-label external Debt via the API — only reachable by
# building the audit row directly).
def _row(**overrides) -> RepaymentDraftAuditRow:
    base = {
        "source": "alipay",
        "amount_cents": 20000,
        "home_currency_code": "CNY",
        "merchant_label": "花呗",
        "captured_at": datetime(2026, 6, 18, 4, 0, tzinfo=UTC),
        "status": "pending",
        "linked_debt_label": None,
        "has_suggestion": False,
        "suggested_debt_label": None,
    }
    base.update(overrides)
    return RepaymentDraftAuditRow(**base)


def test_view_pending_with_suggestion() -> None:
    view = _audit_row_view(
        _row(
            has_suggestion=True,
            suggested_debt_label="花呗",
            suggested_debt_public_id="debt-1",
            target_debts=(
                RepaymentMatchCandidate(
                    public_id="debt-1",
                    counterparty_label="花呗",
                    remaining_amount_cents=50000,
                    row_version=7,
                ),
                RepaymentMatchCandidate(
                    public_id="debt-2",
                    counterparty_label="借呗",
                    remaining_amount_cents=30000,
                    row_version=2,
                ),
            ),
        )
    )
    assert view["status_label"] == "待复核"
    assert view["status_tone"] == ""  # pending is neutral
    assert view["provenance"] == "系统猜测对应:花呗"
    assert view["recede"] is False
    assert view["is_pending"] is True
    assert "linked_line" not in view
    assert view["source_label"] == "支付宝还款"  # mirrors Android source label (§14)
    assert view["amount_label"] == "¥200.00"
    assert view["idempotency_key"]  # 每行一套键 (uuid 文本)
    assert view["targets"] == [
        {
            "public_id": "debt-1",
            "row_version": 7,
            "name": "花呗",
            "remaining_label": "¥500.00",
            "is_suggested": True,  # 服务端建议项拿徽标+主按钮
            "is_selected": False,
        },
        {
            "public_id": "debt-2",
            "row_version": 2,
            "name": "借呗",
            "remaining_label": "¥300.00",
            "is_suggested": False,
            "is_selected": False,
        },
    ]


def test_view_pending_attempted_target_is_marked() -> None:
    # 422 原地重渲染：路由把 attempted target 传回视图，回填「刚才选择」。
    view = _audit_row_view(
        _row(
            target_debts=(
                RepaymentMatchCandidate(
                    public_id="debt-9",
                    counterparty_label=None,  # 防御：无名 → 外部欠款 fallback
                    remaining_amount_cents=30000,
                    row_version=2,
                ),
            ),
        ),
        attempted_target="debt-9",
    )
    assert "provenance" not in view
    assert view["targets"][0]["is_selected"] is True
    assert view["targets"][0]["name"] == "外部欠款"


def test_view_pending_without_targets_has_empty_choices() -> None:
    view = _audit_row_view(_row())
    assert view["targets"] == []
    assert view["is_pending"] is True


def test_view_confirmed_shows_linked_and_not_suggestion() -> None:
    view = _audit_row_view(_row(status="confirmed", linked_debt_label="招商信用卡"))
    assert view["status_label"] == "已记账"
    assert view["status_tone"] == "ok"
    assert view["linked_line"] == "已记到:招商信用卡"
    assert view["is_pending"] is False
    assert "provenance" not in view  # a resolved draft never carries the ephemeral suggestion
    assert "idempotency_key" not in view  # resolved rows carry no action context
    assert view["recede"] is False


def test_view_confirmed_null_label_falls_back_to_external_name() -> None:
    # Defensive fallback: a referenced external Debt always has a label, but the view must
    # never render 「已记到:None」 if it ever were null.
    view = _audit_row_view(_row(status="confirmed", linked_debt_label=None))
    assert view["linked_line"] == "已记到:外部欠款"


def test_view_dismissed_recedes_neutral() -> None:
    view = _audit_row_view(_row(status="dismissed"))
    assert view["status_label"] == "已忽略"
    assert view["status_tone"] == "muted"  # 永不 danger
    assert view["recede"] is True
    assert "idempotency_key" not in view
