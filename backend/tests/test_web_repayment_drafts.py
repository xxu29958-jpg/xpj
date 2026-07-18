"""/web/repayment-drafts 完整还款复核闭环 (ADR-0049 债务域 web 面 slice 3).

列表同时按 selected ledger + capturing account 隔离。pending 可选择当前仍可还的
external/manual Debt，以服务端 row_version 做 OCC、以 actor-scoped idempotency key
确认；也可幂等忽略。confirmed/dismissed 继续保留为沉降的审计历史。

uses ``web_client`` (conftest) 绕过 /web loopback 门(同 test_web_debts);plain ``client``
留门给 remote-403。本文件自包含 seed(经 /api 建草稿/债务 + ORM 直接 seed 成员/二账本),
拆独立文件守 files_over_500(test_web_debts.py 已逼近 500)。
"""

from __future__ import annotations

import re
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, LedgerMember
from app.routes import web_repayment_drafts as web_repayment_drafts_module
from app.routes.web_common import LedgerOption
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


def _confirm(web_client: TestClient, headers: dict[str, str], draft: dict, debt: dict) -> None:
    resp = web_client.post(
        f"/api/repayment-drafts/{draft['public_id']}/confirm",
        headers=_idem(headers),
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]},
    )
    assert resp.status_code == 201, resp.text


def _dismiss(web_client: TestClient, headers: dict[str, str], draft: dict) -> None:
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


def _web_confirm(
    web_client: TestClient,
    *,
    draft: dict,
    debt: dict,
    idempotency_key: str,
    follow_redirects: bool = False,
):
    return web_client.post(
        f"/web/repayment-drafts/{draft['public_id']}/confirm",
        data={
            "ledger_id": "owner",
            "target_debt_public_id": debt["public_id"],
            "expected_row_version": str(debt["row_version"]),
            "idempotency_key": idempotency_key,
            "csrf_token": "test-client-bypasses-middleware-check",
        },
        follow_redirects=follow_redirects,
    )


def _web_dismiss(
    web_client: TestClient,
    *,
    draft: dict,
    follow_redirects: bool = False,
):
    return web_client.post(
        f"/web/repayment-drafts/{draft['public_id']}/dismiss",
        data={
            "ledger_id": "owner",
            "csrf_token": "test-client-bypasses-middleware-check",
        },
        follow_redirects=follow_redirects,
    )


# ── gate + empty ─────────────────────────────────────────────────────────────
def test_web_repayment_drafts_remote_returns_403(client: TestClient) -> None:
    # No loopback / no session override → the LocalOnly gate must 403.
    assert client.get("/web/repayment-drafts").status_code == 403


def test_web_repayment_drafts_empty_renders_premium_empty_state(web_client: TestClient) -> None:
    html = _page(web_client)
    assert "没有待确认的还款" in html
    assert "还款待确认" in html
    assert "product-state" in html
    assert "绝不自动记账" in html
    assert "请在手机 App" not in html


def test_repayment_review_belongs_to_obligations_navigation(
    web_client: TestClient,
) -> None:
    html = _page(web_client)
    obligation_current = re.findall(
        r'<a class="nav-item active"[^>]*href="/web/debts\?ledger_id=owner"'
        r'[^>]*aria-current="location"[^>]*>\s*<span>往来</span>',
        html,
    )
    inbox_current = re.findall(
        r'<a class="nav-item active"[^>]*href="/web/pending\?ledger_id=owner"'
        r'[^>]*aria-current="location"[^>]*>\s*<span>收件</span>',
        html,
    )
    repayment_current = re.findall(
        r'<a class="active"[^>]*href="/web/repayment-drafts\?ledger_id=owner"'
        r'[^>]*aria-current="page"[^>]*>还款复核</a>',
        html,
    )

    assert len(obligation_current) == 2
    assert inbox_current == []
    assert len(repayment_current) == 2


# ── pending row + suggested provenance ───────────────────────────────────────
def test_pending_draft_renders_audit_row(web_client: TestClient, *, identity) -> None:
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    assert "待确认" in html
    assert "支付宝还款" in html  # source label mirrors Android (alipay → 支付宝还款, §14)
    assert "花呗" in html  # merchant
    assert "¥200.00" in html  # amount (home-currency, 20000 cents)


def test_pending_with_matching_debt_shows_suggestion_provenance(web_client: TestClient, *, identity) -> None:
    _create_debt(web_client, identity.app_headers, label="花呗", principal_cents=50000)
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    assert "建议还到「花呗」" in html
    assert "建议 ·" in html
    assert "花呗 · 还剩 ¥500.00" in html
    assert "确认" in html
    assert 'type="submit"' in html
    assert ">忽略</button>" in html
    assert 'name="csrf_token"' in html
    assert 'name="expected_row_version"' in html


def test_pending_without_match_shows_no_provenance(web_client: TestClient, *, identity) -> None:
    # No repayable Debt at all → no confident suggestion → no provenance line.
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    assert "待确认" in html
    assert "建议还到" not in html


def test_pending_picker_excludes_a_debt_that_cannot_cover_the_draft(web_client: TestClient, *, identity) -> None:
    _create_debt(
        web_client,
        identity.app_headers,
        label="额度不足的欠款",
        principal_cents=5000,
    )
    _create_draft(
        web_client,
        identity.app_headers,
        merchant_label="额度不足的欠款",
        amount_cents=10000,
    )

    html = _page(web_client)

    assert "没有可对应的欠款" in html
    assert "额度不足的欠款 · 还剩" not in html
    assert 'href="/web/debts/new?ledger_id=owner"' in html
    assert ">忽略</button>" in html


def test_confirm_is_occ_backed_and_idempotent(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(
        web_client,
        identity.app_headers,
        label="招商信用卡",
        principal_cents=50000,
    )
    draft = _create_draft(
        web_client,
        identity.app_headers,
        merchant_label="信用卡",
        amount_cents=10000,
    )
    key = str(uuid4())

    first = _web_confirm(
        web_client,
        draft=draft,
        debt=debt,
        idempotency_key=key,
    )
    replay = _web_confirm(
        web_client,
        draft=draft,
        debt=debt,
        idempotency_key=key,
    )

    assert first.status_code == 303
    assert replay.status_code == 303
    confirmed = web_client.get(
        "/api/repayment-drafts?status=confirmed",
        headers=identity.app_headers,
    ).json()["items"]
    assert [item["public_id"] for item in confirmed] == [draft["public_id"]]
    current_debt = web_client.get(
        f"/api/debts/{debt['public_id']}",
        headers=identity.app_headers,
    )
    assert current_debt.status_code == 200, current_debt.text
    assert current_debt.json()["remaining_amount_cents"] == 40000


def test_confirm_validation_keeps_selected_draft_and_idempotency_key(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(
        web_client,
        identity.app_headers,
        label="花呗-可选欠款",
        principal_cents=50000,
    )
    draft = _create_draft(
        web_client,
        identity.app_headers,
        merchant_label="花呗-保留输入",
        amount_cents=10000,
    )
    key = str(uuid4())

    response = web_client.post(
        f"/web/repayment-drafts/{draft['public_id']}/confirm",
        data={
            "ledger_id": "owner",
            "target_debt_public_id": debt["public_id"],
            "expected_row_version": "stale-token",
            "idempotency_key": key,
            "csrf_token": "test-client-bypasses-middleware-check",
        },
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert "欠款信息已经失效，请刷新后重新选择。" in response.text
    assert "花呗-保留输入" in response.text
    assert "（刚才选择）" in response.text
    assert f'value="{key}"' in response.text
    pending = web_client.get(
        "/api/repayment-drafts?status=pending",
        headers=identity.app_headers,
    ).json()["items"]
    assert [item["public_id"] for item in pending] == [draft["public_id"]]


def test_dismiss_is_repeat_safe_and_stays_in_audit_history(web_client: TestClient, *, identity) -> None:
    draft = _create_draft(
        web_client,
        identity.app_headers,
        merchant_label="白条-忽略",
        amount_cents=8000,
    )

    first = _web_dismiss(web_client, draft=draft)
    replay = _web_dismiss(web_client, draft=draft)
    html = _page(web_client)

    assert first.status_code == 303
    assert replay.status_code == 303
    assert "白条-忽略" in html
    assert "已忽略" in html
    assert "is-receded" in html


def test_confirm_cannot_resolve_another_accounts_capture(web_client: TestClient, *, identity) -> None:
    member = _seed_member_token(name="另一位家人")
    member_draft = _create_draft(
        web_client,
        member,
        merchant_label="另一位家人的花呗",
        amount_cents=10000,
    )
    owner_debt = _create_debt(
        web_client,
        identity.app_headers,
        label="我的花呗",
        principal_cents=50000,
    )

    response = _web_confirm(
        web_client,
        draft=member_draft,
        debt=owner_debt,
        idempotency_key=str(uuid4()),
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    member_pending = web_client.get(
        "/api/repayment-drafts?status=pending",
        headers=member,
    ).json()["items"]
    assert [item["public_id"] for item in member_pending] == [member_draft["public_id"]]


def test_selected_ledger_viewer_cannot_confirm(web_client: TestClient, *, identity, monkeypatch) -> None:
    debt = _create_debt(web_client, identity.app_headers)
    draft = _create_draft(web_client, identity.app_headers)
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

    response = _web_confirm(
        web_client,
        draft=draft,
        debt=debt,
        idempotency_key=str(uuid4()),
    )

    assert response.status_code == 403
    pending = web_client.get(
        "/api/repayment-drafts?status=pending",
        headers=identity.app_headers,
    ).json()["items"]
    assert [item["public_id"] for item in pending] == [draft["public_id"]]


# ── confirmed (linked debt) + label fallback ─────────────────────────────────
def test_confirmed_draft_shows_linked_debt(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(web_client, identity.app_headers, label="招商信用卡", principal_cents=50000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="信用卡", amount_cents=10000)
    _confirm(web_client, identity.app_headers, draft, debt)
    html = _page(web_client)
    assert "已记账" in html
    assert "已记到「招商信用卡」" in html
    # A resolved draft never carries the ephemeral suggestion provenance.
    assert "建议还到" not in html


# (No fallback-name test: 外部债建账强制非空 counterparty_label〔422 without〕 and confirm only
# targets external/manual Debt, so a referenced Debt always has a label — the route's 外部欠款
# fallback is defensive-only, an unconstructable state, so there is nothing real to pin.)


# ── dismissed (sunk) ─────────────────────────────────────────────────────────
def test_dismissed_draft_receded_and_ignored_label(web_client: TestClient, *, identity) -> None:
    draft = _create_draft(web_client, identity.app_headers, merchant_label="白条", amount_cents=8000)
    _dismiss(web_client, identity.app_headers, draft)
    html = _page(web_client)
    assert "已忽略" in html
    assert "is-receded" in html  # dismissed rows recede (永不红)


# ── account + selected-ledger scope ──────────────────────────────────────────
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
    # The same account can participate in multiple ledgers, but the review form's
    # writer/OCC authority is the selected ledger. A second-ledger capture must not
    # appear or become actionable in the owner-ledger inbox.
    _create_draft(web_client, identity.app_headers, merchant_label="花呗-本账本", amount_cents=10000)
    _create_debt(web_client, identity.gray_app_headers, label="工行信用卡", principal_cents=50000)
    _create_draft(web_client, identity.gray_app_headers, merchant_label="信用卡-二账本", amount_cents=10000)
    html = _page(web_client)
    assert "花呗-本账本" in html  # own ledger capture
    assert "信用卡-二账本" not in html
    assert "工行信用卡" not in html


def test_selected_ledger_action_cannot_resolve_another_ledgers_draft(web_client: TestClient, *, identity) -> None:
    other_draft = _create_draft(
        web_client,
        identity.gray_app_headers,
        merchant_label="二账本草稿",
        amount_cents=10000,
    )
    owner_debt = _create_debt(
        web_client,
        identity.app_headers,
        label="本账本欠款",
        principal_cents=50000,
    )

    response = _web_confirm(
        web_client,
        draft=other_draft,
        debt=owner_debt,
        idempotency_key=str(uuid4()),
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    other_pending = web_client.get(
        "/api/repayment-drafts?status=pending",
        headers=identity.gray_app_headers,
    ).json()["items"]
    assert [item["public_id"] for item in other_pending] == [other_draft["public_id"]]


def test_newest_first_ordering(web_client: TestClient, *, identity) -> None:
    _create_draft(web_client, identity.app_headers, merchant_label="先记的", amount_cents=10000)
    _create_draft(web_client, identity.app_headers, merchant_label="后记的", amount_cents=11000)
    html = _page(web_client)
    assert html.index("后记的") < html.index("先记的")  # newest-first
