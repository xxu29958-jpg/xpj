"""Personal capture review: shared command semantics, original values and history."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, LedgerMember
from app.routes import web_repayment_drafts as web_repayment_drafts_module
from app.routes.web_common import LedgerOption
from app.services.identity_service import hash_secret, new_session_token
from tests._runtime_protocol import current_protocol_headers, negotiated_headers


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
        "home_currency_code": "CNY", "direction": "i_owe",
        "counterparty_type": "external",
        "principal_amount_cents": principal_cents,
    }
    if label is not None:
        body["counterparty_label"] = label
    resp = web_client.post("/api/debts", headers=negotiated_headers(web_client, _idem(headers)), json=body)
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
        return current_protocol_headers({"Authorization": f"Bearer {token}"})


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
    original_amount: str | None = None,
):
    return web_client.post(
        f"/web/repayment-drafts/{draft['public_id']}/review",
        data={
            "ledger_id": "owner",
            "draft_public_id": draft["public_id"], "origin_binding": "{}", "review_action": "confirm",
            "target_choice": f"{debt['public_id']}:{debt['row_version'] if row_version is None else row_version}",
            "original_currency": draft["original_currency_code"],
            "original_amount": original_amount if original_amount is not None else str(Decimal(draft["original_amount_minor"]).scaleb(-2)),
            "idempotency_key": str(uuid4()) if idempotency_key is None else idempotency_key,
            "csrf_token": "test-client-bypasses-middleware-check",
        },
        follow_redirects=False,
    )


def _web_dismiss(web_client: TestClient, *, draft: dict):
    return web_client.post(
        f"/web/repayment-drafts/{draft['public_id']}/review",
        data={
            "ledger_id": "owner", "draft_public_id": draft["public_id"],
            "origin_binding": "{}", "review_action": "dismiss", "idempotency_key": str(uuid4()),
            "csrf_token": "test-client-bypasses-middleware-check",
        },
        follow_redirects=False,
    )


def _drafts_via_api(web_client: TestClient, headers: dict[str, str], status: str) -> list[dict]:
    return web_client.get(f"/api/repayment-drafts?status={status}", headers=headers).json()["items"]


# ── access and original review ───────────────────────────────────────────────
def test_web_repayment_drafts_remote_returns_403(client: TestClient) -> None:
    # No loopback / no session override → the LocalOnly gate must 403.
    assert client.get("/web/repayment-drafts").status_code == 403


# ── pending row, original review and suggested provenance ────────────────────
def test_pending_draft_renders_audit_row(web_client: TestClient, *, identity) -> None:
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    assert "待复核" in html
    assert "支付宝还款" in html  # source label mirrors Android (alipay → 支付宝还款, §14)
    assert "花呗" in html  # merchant
    assert "¥200.00" in html  # amount (home-currency, 20000 cents)


def test_pending_opens_one_original_review_with_target_version(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(web_client, identity.app_headers, label="花呗", principal_cents=50000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    listing = _page(web_client)
    assert f'/web/repayment-drafts/{draft["public_id"]}?ledger_id=owner' in listing
    assert 'name="idempotency_key"' not in listing
    detail = web_client.get(f"/web/repayment-drafts/{draft['public_id']}?ledger_id=owner")
    assert detail.status_code == 200
    assert "系统猜测对应:花呗" in detail.text
    assert f'value="{debt["public_id"]}:{debt["row_version"]}" selected' in detail.text
    assert "花呗 · 剩余 ¥500.00" in detail.text
    assert 'name="original_amount"' in detail.text
    assert 'data-repayment-kind="repayment-review"' in detail.text


def test_pending_without_match_shows_no_provenance(web_client: TestClient, *, identity) -> None:
    # No repayable Debt at all → no confident suggestion → no provenance line.
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    assert "待复核" in html
    assert "系统猜测对应" not in html


def test_review_can_correct_captured_money_before_remaining_check(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(web_client, identity.app_headers, label="可还 90 元的欠款", principal_cents=9000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="原采集 100 元", amount_cents=10000)
    detail = web_client.get(f"/web/repayment-drafts/{draft['public_id']}?ledger_id=owner")
    assert "可还 90 元的欠款 · 剩余 ¥90.00" in detail.text
    response = _web_confirm(web_client, draft=draft, debt=debt, original_amount="80.00")
    assert response.status_code == 200, response.text
    current = web_client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    assert current["remaining_amount_cents"] == 1000
    resolved = _drafts_via_api(web_client, identity.app_headers, "confirmed")[0]
    assert resolved["original_amount_minor"] == 10000
    assert f'/web/debts/{debt["public_id"]}?ledger_id=owner' in response.text


# ── confirm: idempotent + OCC ────────────────────────────────────────────────
def test_confirm_is_occ_backed_and_idempotent(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(web_client, identity.app_headers, label="招商信用卡", principal_cents=50000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="信用卡", amount_cents=10000)
    key = str(uuid4())

    first = _web_confirm(web_client, draft=draft, debt=debt, idempotency_key=key)
    replay = _web_confirm(web_client, draft=draft, debt=debt, idempotency_key=key)

    assert first.status_code == 200
    assert replay.status_code == 200  # 重放返回 canonical 结果，不再记第二笔
    confirmed = _drafts_via_api(web_client, identity.app_headers, "confirmed")
    assert [item["public_id"] for item in confirmed] == [draft["public_id"]]
    current = web_client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert current.status_code == 200, current.text
    assert current.json()["remaining_amount_cents"] == 40000


def test_confirm_malformed_token_retains_the_original_key_and_choice(
    web_client: TestClient, *, identity
) -> None:
    debt = _create_debt(web_client, identity.app_headers, label="花呗-可选欠款", principal_cents=50000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="花呗-保留行", amount_cents=10000)
    key = str(uuid4())

    response = _web_confirm(web_client, draft=draft, debt=debt, row_version="stale-token", idempotency_key=key)

    assert response.status_code == 422
    assert "请选择欠款并核对它的当前版本。" in response.text
    assert "花呗-保留行" in response.text  # 原地重渲染：捕获行还在
    assert 'role="alert"' in response.text  # 错误锚定到该 row (aria)
    assert f'value="{debt["public_id"]}:stale-token" selected' in response.text
    assert 'name="idempotency_key"' in response.text  # 表单立即可重试
    assert f'value="{key}"' in response.text  # 业务校验失败保留已提交键：重试仍命中同一 claim
    assert [item["public_id"] for item in _drafts_via_api(web_client, identity.app_headers, "pending")] == [
        draft["public_id"]
    ]


def test_confirm_stale_row_version_retains_original_and_stays_pending(
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

    assert response.status_code == 409
    assert f'value="{debt["public_id"]}:{stale_version}" selected' in response.text
    assert 'data-void-rejected="true"' in response.text
    assert [item["public_id"] for item in _drafts_via_api(web_client, identity.app_headers, "pending")] == [
        draft["public_id"]
    ]
    # The first repayment is untouched (exactly one confirmed).
    assert len(_drafts_via_api(web_client, identity.app_headers, "confirmed")) == 1


def test_confirm_without_idempotency_key_rerenders_422(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(web_client, identity.app_headers, principal_cents=50000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="缺键", amount_cents=10000)
    resp = _web_confirm(web_client, draft=draft, debt=debt, idempotency_key="")
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

    assert response.status_code == 404
    assert [item["public_id"] for item in _drafts_via_api(web_client, member, "pending")] == [
        member_draft["public_id"]
    ]


def test_selected_ledger_action_cannot_resolve_another_ledgers_draft(
    web_client: TestClient, *, identity
) -> None:
    other_draft = _create_draft(web_client, identity.gray_app_headers, merchant_label="二账本草稿", amount_cents=10000)
    owner_debt = _create_debt(web_client, identity.app_headers, label="本账本欠款", principal_cents=50000)

    response = _web_confirm(web_client, draft=other_draft, debt=owner_debt)

    assert response.status_code == 404
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
    assert "核对并处理" not in html


# ── dismiss: replay-safe terminal flip ───────────────────────────────────────
def test_dismiss_is_repeat_safe_and_stays_in_audit_history(web_client: TestClient, *, identity) -> None:
    draft = _create_draft(web_client, identity.app_headers, merchant_label="白条-忽略", amount_cents=8000)

    first = _web_dismiss(web_client, draft=draft)
    replay = _web_dismiss(web_client, draft=draft)
    html = _page(web_client)

    assert first.status_code == 200
    assert replay.status_code == 200  # 终态翻转幂等：重复忽略不报错
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

