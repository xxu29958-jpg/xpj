"""/web/repayment-drafts 还款捕获审计页 (ADR-0049 债务域 web 面 slice 3).

只读 **account-scoped** 审计日志:列 viewer **自己创建的** NLS 还款捕获 (隐私边界——
还款通知是个人的,不暴露其他成员的),跨该账户所有账本、新近排序。pending→待复核 + 描述性
provenance「系统猜测对应:<对手方>」(ephemeral 建议债);confirmed→已记账 + 关联债;dismissed→
已忽略 沉降。actionable (选债/确认/忽略) 全留 Android + /api,这里纯只读。

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
from app.routes.web_repayment_drafts import _audit_row_view
from app.services.debt_service import RepaymentDraftAuditRow
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
    resp = web_client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=headers, json={}
    )
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


# ── gate + empty ─────────────────────────────────────────────────────────────
def test_web_repayment_drafts_remote_returns_403(client: TestClient) -> None:
    # No loopback / no session override → the LocalOnly gate must 403.
    assert client.get("/web/repayment-drafts").status_code == 403


def test_web_repayment_drafts_empty_renders_premium_empty_state(web_client: TestClient) -> None:
    html = _page(web_client)
    assert "还没有还款捕获" in html
    assert "dt-card--empty" in html
    assert "只读审计:复核与确认请在手机 App。" in html


# ── pending row + suggested provenance ───────────────────────────────────────
def test_pending_draft_renders_audit_row(web_client: TestClient, *, identity) -> None:
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    assert "待复核" in html
    assert "支付宝还款" in html  # source label mirrors Android (alipay → 支付宝还款, §14)
    assert "花呗" in html  # merchant
    assert "¥200.00" in html  # amount (home-currency, 20000 cents)


def test_pending_with_matching_debt_shows_suggestion_provenance(
    web_client: TestClient, *, identity
) -> None:
    _create_debt(web_client, identity.app_headers, label="花呗", principal_cents=50000)
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    # Server-suggested Debt rendered as descriptive provenance, NOT an actionable pre-select.
    assert "系统猜测对应:花呗" in html


def test_pending_without_match_shows_no_provenance(web_client: TestClient, *, identity) -> None:
    # No repayable Debt at all → no confident suggestion → no provenance line.
    _create_draft(web_client, identity.app_headers, merchant_label="花呗", amount_cents=20000)
    html = _page(web_client)
    assert "待复核" in html
    assert "系统猜测对应" not in html


# ── confirmed (linked debt) + label fallback ─────────────────────────────────
def test_confirmed_draft_shows_linked_debt(web_client: TestClient, *, identity) -> None:
    debt = _create_debt(web_client, identity.app_headers, label="招商信用卡", principal_cents=50000)
    draft = _create_draft(web_client, identity.app_headers, merchant_label="信用卡", amount_cents=10000)
    _confirm(web_client, identity.app_headers, draft, debt)
    html = _page(web_client)
    assert "已记账" in html
    assert "已记到:招商信用卡" in html
    # A resolved draft never carries the ephemeral suggestion provenance.
    assert "系统猜测对应" not in html


# (No fallback-name test: 外部债建账强制非空 counterparty_label〔422 without〕 and confirm only
# targets external/manual Debt, so a referenced Debt always has a label — the route's 外部欠款
# fallback is defensive-only, an unconstructable state, so there is nothing real to pin.)


# ── dismissed (sunk) ─────────────────────────────────────────────────────────
def test_dismissed_draft_receded_and_ignored_label(web_client: TestClient, *, identity) -> None:
    draft = _create_draft(web_client, identity.app_headers, merchant_label="白条", amount_cents=8000)
    _dismiss(web_client, identity.app_headers, draft)
    html = _page(web_client)
    assert "已忽略" in html
    assert "debt-card-sunk" in html  # dismissed rows recede (永不红)


# ── account-scoped (privacy) + cross-ledger (非 ledger-scoped) ────────────────
def test_account_scoped_hides_other_members_captures(web_client: TestClient, *, identity) -> None:
    # Owner's own capture shows; a SECOND member's capture in the SAME ledger must NOT
    # (account-scoped, not ledger-scoped — repayment notifications are private).
    _create_draft(web_client, identity.app_headers, merchant_label="花呗-我的", amount_cents=10000)
    member = _seed_member_token(name="家人")
    _create_draft(web_client, member, merchant_label="借呗-家人的", amount_cents=9000)
    html = _page(web_client)
    assert "花呗-我的" in html  # viewer (owner) sees own capture
    assert "借呗-家人的" not in html  # member's private capture hidden from the owner's view


def test_cross_ledger_captures_aggregate_and_resolve_labels(
    web_client: TestClient, *, identity
) -> None:
    # The owner account captures in a SECOND ledger (tester_1 via gray_app_headers). The
    # account-scoped audit shows it on the owner-ledger view (非 ledger-scoped), and the
    # cross-tenant committed-Debt label still resolves (global public_id lookup).
    _create_draft(web_client, identity.app_headers, merchant_label="花呗-本账本", amount_cents=10000)
    other_debt = _create_debt(web_client, identity.gray_app_headers, label="工行信用卡", principal_cents=50000)
    other_draft = _create_draft(
        web_client, identity.gray_app_headers, merchant_label="信用卡-二账本", amount_cents=10000
    )
    _confirm(web_client, identity.gray_app_headers, other_draft, other_debt)
    html = _page(web_client)
    assert "花呗-本账本" in html  # own ledger capture
    assert "信用卡-二账本" in html  # cross-ledger capture aggregated
    assert "已记到:工行信用卡" in html  # cross-tenant linked-Debt label resolved


def test_newest_first_ordering(web_client: TestClient, *, identity) -> None:
    _create_draft(web_client, identity.app_headers, merchant_label="先记的", amount_cents=10000)
    _create_draft(web_client, identity.app_headers, merchant_label="后记的", amount_cents=11000)
    html = _page(web_client)
    assert html.index("后记的") < html.index("先记的")  # newest-first


# ── _audit_row_view pure unit (status tones + provenance/linked prefixes + 防御 fallback) ──
# Pin the view dict directly: the HTTP tests check rendered HTML substrings (labels), but not
# the pill TONE (ok/muted/"") or the defensive 外部欠款 fallback (an unconstructable null-label
# external Debt via the API — only reachable by building the audit row directly).
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
    view = _audit_row_view(_row(has_suggestion=True, suggested_debt_label="花呗"))
    assert view["status_label"] == "待复核"
    assert view["status_tone"] == ""  # pending is neutral
    assert view["provenance"] == "系统猜测对应:花呗"
    assert view["recede"] is False
    assert "linked_line" not in view
    assert view["source_label"] == "支付宝还款"  # mirrors Android source label (§14)
    assert view["amount_label"] == "¥200.00"


def test_view_pending_without_suggestion_has_no_provenance() -> None:
    view = _audit_row_view(_row(has_suggestion=False))
    assert view["status_label"] == "待复核"
    assert "provenance" not in view


def test_view_confirmed_shows_linked_and_not_suggestion() -> None:
    view = _audit_row_view(_row(status="confirmed", linked_debt_label="招商信用卡"))
    assert view["status_label"] == "已记账"
    assert view["status_tone"] == "ok"
    assert view["linked_line"] == "已记到:招商信用卡"
    assert "provenance" not in view  # a resolved draft never carries the ephemeral suggestion
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
