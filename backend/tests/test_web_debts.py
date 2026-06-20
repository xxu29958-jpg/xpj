"""/web/debts page (ADR-0049 债务域 web 面 slice 1 — 只读欠款列表)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Debt, LedgerMember
from app.routes.web_common import _amount_segments
from app.routes.web_debts import (
    _communal_ratio,
    _debt_view,
    _detail_view,
    _member_headline,
    _split_debt_views,
)

# Uses the shared ``web_client`` fixture (conftest.py) which bypasses the /web
# loopback gate by overriding _require_local; the plain ``client`` fixture keeps
# the gate for the remote-403 test.


def _idem(app_headers: dict[str, str]) -> dict[str, str]:
    return {**app_headers, "Idempotency-Key": str(uuid4())}


def _create_external_debt(
    web_client: TestClient,
    *,
    identity,
    direction: str = "i_owe",
    label: str | None = "招商信用卡",
    principal_cents: int = 50000,
) -> dict:
    body: dict[str, object] = {
        "direction": direction,
        "counterparty_type": "external",
        "principal_amount_cents": principal_cents,
    }
    if label is not None:
        body["counterparty_label"] = label
    resp = web_client.post("/api/debts", headers=_idem(identity.app_headers), json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed_member_debt(*, direction: str = "i_owe", principal_cents: int = 12000) -> str:
    """Seed a committed member (bill_split) Debt directly via ORM.

    ``POST /api/debts`` only creates external debt (a member obligation needs the
    other party's confirmation — it arrives via bill_split accept), so member debts
    are inserted directly. No counterparty_label → exercises the 家庭成员 fallback.
    """
    with SessionLocal() as db:
        member = Account(display_name="家人")
        db.add(member)
        db.flush()
        owner_account_id = db.scalar(
            select(LedgerMember.account_id)
            .where(LedgerMember.ledger_id == "owner")
            .order_by(LedgerMember.id.asc())
            .limit(1)
        )
        assert owner_account_id is not None
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_account_id,
            created_by_account_id=owner_account_id,
            direction=direction,
            counterparty_type="member",
            counterparty_account_id=member.id,
            principal_amount_cents=principal_cents,
            home_currency_code="CNY",
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.commit()
        return debt.public_id


def test_web_debts_remote_returns_403(client: TestClient) -> None:
    # No loopback / no session override → the LocalOnly gate must 403.
    resp = client.get("/web/debts")
    assert resp.status_code == 403


def test_web_debts_empty_renders(web_client: TestClient) -> None:
    resp = web_client.get("/web/debts")
    assert resp.status_code == 200
    assert "欠款" in resp.text
    # Empty-state copy mirrors the Android debt_list_empty_* strings.
    assert "还没有欠款记录" in resp.text


def test_web_debts_lists_external_i_owe_open(web_client: TestClient, *, identity) -> None:
    _create_external_debt(web_client, identity=identity, direction="i_owe")
    resp = web_client.get("/web/debts")
    assert resp.status_code == 200
    assert "招商信用卡" in resp.text
    assert "应付" in resp.text  # i_owe direction label
    assert "未结清" in resp.text  # open status label
    assert "本金" in resp.text
    assert "500.00" in resp.text  # home-currency principal footnote
    # Editorial-split remaining hero (cur/int/dec spans), not a blunt label string.
    assert "dh-amt--row" in resp.text
    assert '<span class="dh-int">500</span>' in resp.text


def test_web_debts_renders_owed_to_me_direction(web_client: TestClient, *, identity) -> None:
    _create_external_debt(
        web_client, identity=identity, direction="owed_to_me", label="同事借款"
    )
    resp = web_client.get("/web/debts")
    assert resp.status_code == 200
    assert "同事借款" in resp.text
    assert "应收" in resp.text  # owed_to_me direction label


def test_web_debts_renders_cleared_status_and_zero_remaining(
    web_client: TestClient, *, identity
) -> None:
    debt = _create_external_debt(web_client, identity=identity, principal_cents=50000)
    # Full repayment clears the Debt (remaining → 0, status → cleared).
    repay = web_client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 50000, "expected_row_version": debt["row_version"]},
    )
    assert repay.status_code == 201, repay.text
    resp = web_client.get("/web/debts")
    assert resp.status_code == 200
    assert "已结清" in resp.text  # cleared status label
    assert "dt-pill ok" in resp.text  # cleared → success tone class rendered
    # Remaining hero integer is now exactly 0 (the only dh-int in the row; principal
    # stays a plain footnote, so this precisely checks remaining == 0).
    assert '<span class="dh-int">0</span>' in resp.text
    assert "本金 " in resp.text  # principal footnote still shown


def test_web_debts_renders_voided_status(web_client: TestClient, *, identity) -> None:
    debt = _create_external_debt(web_client, identity=identity, label="作废测试欠款")
    voided = web_client.post(
        f"/api/debts/{debt['public_id']}/void",
        headers=_idem(identity.app_headers),
        json={"reason": "记错了", "expected_row_version": debt["row_version"]},
    )
    assert voided.status_code == 201, voided.text
    resp = web_client.get("/web/debts")
    assert resp.status_code == 200
    assert "已作废" in resp.text  # voided status label
    assert "dt-pill danger" in resp.text  # voided → danger tone class rendered


def _seed_third_party_member_debt() -> str:
    """Seed an 'owner'-ledger member debt between two OTHER accounts, so the ledger owner
    (the web/loopback viewer) is a THIRD party. Proves the row computes viewer_is_debtor per
    VIEWER, not from owner-relative direction (a direction-based row would mis-frame it)."""
    with SessionLocal() as db:
        debtor = Account(display_name="弟弟")
        creditor = Account(display_name="妹妹")
        db.add_all([debtor, creditor])
        db.flush()
        debt = Debt(
            tenant_id="owner",
            owner_account_id=debtor.id,  # Debt owner = debtor, NOT the ledger owner (the viewer)
            created_by_account_id=debtor.id,
            direction="i_owe",
            counterparty_type="member",
            counterparty_account_id=creditor.id,
            counterparty_label="妹妹",
            principal_amount_cents=10000,
            home_currency_code="CNY",
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.commit()
        return debt.public_id


def test_web_debts_lists_member_debt_communal(web_client: TestClient) -> None:
    # slice 1A: member (bill_split) debts render as a COMMUNAL relational row, not the
    # accounting framing. The viewer (loopback owner = the i_owe debtor) sees the relational
    # headline + 家人 section header + neutral status, NEVER 应付/应收 and NEVER danger (red-line ②).
    # No counterparty_label → the 家庭成员 fallback. (Drop the viewer pass → headline degrades to
    # the third-party "这件事还在进行中" and this fails.)
    _seed_member_debt(direction="i_owe")
    resp = web_client.get("/web/debts")
    assert resp.status_code == 200
    assert "家庭成员" in resp.text  # counterparty fallback name
    assert '<h2 class="debt-section-title">家人</h2>' in resp.text  # 家人 section header
    # Communal relational headline (viewer=owner=debtor, open, ratio 0).
    assert "你帮我垫了，慢慢还给你" in resp.text
    assert "进行中" in resp.text  # member open status badge (neutral)
    # Red lines: a member row never shows the accounting framing.
    assert "应付" not in resp.text
    assert "应收" not in resp.text
    # No external debts seeded → no 外部 section.
    assert '<h2 class="debt-section-title">外部</h2>' not in resp.text


def test_web_debts_groups_family_before_external(web_client: TestClient, *, identity) -> None:
    # slice 1A soft-grouping: 家人 section first (single scroll), then 外部. Family rows are
    # communal; external rows keep the accounting labels (应付). No list-level scoreboard.
    _seed_member_debt(direction="i_owe")
    _create_external_debt(web_client, identity=identity, direction="i_owe", label="招商信用卡")
    resp = web_client.get("/web/debts")
    assert resp.status_code == 200
    fam = '<h2 class="debt-section-title">家人</h2>'
    ext = '<h2 class="debt-section-title">外部</h2>'
    assert fam in resp.text
    assert ext in resp.text
    assert resp.text.index(fam) < resp.text.index(ext)  # 家人 before 外部
    assert "你帮我垫了，慢慢还给你" in resp.text  # family communal headline
    assert "招商信用卡" in resp.text  # external row
    assert "应付" in resp.text  # external still uses the accounting direction label


def test_web_debts_member_row_third_party_viewer(web_client: TestClient) -> None:
    # The viewer (ledger owner) is neither the debtor nor the creditor → third-party relational
    # framing, NOT the owner-relative "你帮我垫的" a direction-based row would wrongly show. This
    # pins that the row honors the VIEWER's account, not the Debt's stored owner.
    _seed_third_party_member_debt()
    resp = web_client.get("/web/debts")
    assert resp.status_code == 200
    assert "这件事还在进行中" in resp.text  # third-party headline
    assert "你帮我垫" not in resp.text
    assert "我帮你垫" not in resp.text
    assert "dt-pill danger" not in resp.text  # never red for a member row


def _stub_debt(**overrides) -> SimpleNamespace:
    base = {
        "public_id": "dbt_1",
        "counterparty_label": "招商信用卡",
        "counterparty_type": "external",
        "direction": "i_owe",
        "status": "open",
        "remaining_amount_cents": 50000,
        "principal_amount_cents": 50000,
        "paid_amount_cents": 0,
        "home_currency_code": "CNY",
        "original_currency_code": None,
        "viewer_is_debtor": None,
        "is_forgiven": False,
        # §B installment fields — defaulted so a plain external/member stub yields installment=None
        # through _installment_view (non-installment → no schedule card); installment tests override them.
        "debt_kind": "unspecified",
        "installment_count": None,
        "installment_period_months": None,
        "installment_paid_count": None,
        "installment_payoff_date": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_debt_view_maps_labels_tones_and_fallbacks() -> None:
    """Pure view-model mapping (direction/status labels + tones + name fallbacks)."""
    # Direction labels mirror Android debtDirectionLabelRes.
    assert _debt_view(_stub_debt(direction="i_owe"))["direction_label"] == "应付"
    assert _debt_view(_stub_debt(direction="owed_to_me"))["direction_label"] == "应收"
    # Status labels + tones mirror debtLinkStatusLabelRes / debtLinkStatusTone.
    open_view = _debt_view(_stub_debt(status="open"))
    assert (open_view["status_label"], open_view["status_tone"]) == ("未结清", "")
    cleared_view = _debt_view(_stub_debt(status="cleared"))
    assert (cleared_view["status_label"], cleared_view["status_tone"]) == ("已结清", "ok")
    voided_view = _debt_view(_stub_debt(status="voided"))
    assert (voided_view["status_label"], voided_view["status_tone"]) == ("已作废", "danger")
    # Name uses the label when present; falls back per counterparty_type when blank.
    assert _debt_view(_stub_debt(counterparty_label="房东"))["name"] == "房东"
    member_blank = _debt_view(_stub_debt(counterparty_type="member", counterparty_label=None))
    assert member_blank["name"] == "家庭成员"
    external_blank = _debt_view(
        _stub_debt(counterparty_type="external", counterparty_label="   ")
    )
    assert external_blank["name"] == "外部欠款"
    # Remaining hero is exposed as cur/int/dec segments for the editorial split.
    seg = _debt_view(_stub_debt(remaining_amount_cents=123456))["remaining_segments"]
    assert seg == {"cur": "¥", "int": "1,234", "dec": ".56"}


def test_debt_view_member_branch_is_communal() -> None:
    """A member row is communal: relational headline + neutral/success status, NO accounting
    fields (direction_label / remaining_segments), recede when terminal."""
    # Open member debt, viewer=debtor, zero paid → start headline, neutral status, progress shown.
    member = _debt_view(
        _stub_debt(counterparty_type="member", counterparty_label="爸爸",
                   viewer_is_debtor=True, status="open", paid_amount_cents=0)
    )
    assert member["is_member"] is True
    assert member["member_headline"] == "你帮我垫了，慢慢还给你"
    assert member["show_progress"] is True
    assert member["ratio_percent"] == 0
    assert (member["member_status_label"], member["member_status_tone"]) == ("进行中", "")
    assert member["recede"] is False
    # A member row never carries the external accounting fields.
    assert "direction_label" not in member
    assert "remaining_segments" not in member

    # Cleared member debt → recede (sunk), success status, no progress bar.
    cleared = _debt_view(
        _stub_debt(counterparty_type="member", viewer_is_debtor=True, status="cleared",
                   paid_amount_cents=12000, principal_amount_cents=12000)
    )
    assert cleared["member_headline"] == "这件事，我们已经两清啦"
    assert (cleared["member_status_label"], cleared["member_status_tone"]) == ("已两清", "ok")
    assert cleared["show_progress"] is False
    assert cleared["recede"] is True

    # Forgiven member debt (cleared + is_forgiven) → the warm 被请客 headline, NOT plain 两清.
    # Pins that _debt_view threads debt.is_forgiven into _member_headline (a mutation hardcoding
    # is_forgiven=False would silently downgrade this to "我们已经两清啦" and only this asserts it).
    forgiven = _debt_view(
        _stub_debt(counterparty_type="member", viewer_is_debtor=True, status="cleared",
                   is_forgiven=True, paid_amount_cents=12000, principal_amount_cents=12000)
    )
    assert forgiven["member_headline"] == "这份 TA 说不用还啦 ❤️"

    # Voided member debt → neutral status (NEVER danger, red-line ②) + recede.
    voided = _debt_view(_stub_debt(counterparty_type="member", status="voided"))
    assert voided["member_status_tone"] == ""  # neutral, not danger
    assert voided["recede"] is True

    # Foreign-currency member debt → falls back to the external accounting row (FX defense).
    foreign = _debt_view(
        _stub_debt(counterparty_type="member", original_currency_code="USD", status="open")
    )
    assert foreign["is_member"] is False
    assert "direction_label" in foreign


def test_split_debt_views_groups_and_sorts_active_first() -> None:
    """家人/外部 split with active-first ordering (open before cleared/voided) inside each group."""
    items = [
        _stub_debt(public_id="m_cleared", counterparty_type="member", status="cleared",
                   viewer_is_debtor=True, paid_amount_cents=100, principal_amount_cents=100),
        _stub_debt(public_id="e_voided", counterparty_type="external", status="voided"),
        _stub_debt(public_id="m_open", counterparty_type="member", status="open",
                   viewer_is_debtor=True),
        _stub_debt(public_id="e_open", counterparty_type="external", status="open"),
        # Foreign member debt sorts into the EXTERNAL group (FX fallback).
        _stub_debt(public_id="m_foreign", counterparty_type="member",
                   original_currency_code="USD", status="open"),
    ]
    members, externals = _split_debt_views(items)
    assert [v["public_id"] for v in members] == ["m_open", "m_cleared"]  # open before cleared
    assert [v["public_id"] for v in externals] == ["e_open", "m_foreign", "e_voided"]  # open first


def test_amount_segments_splits_cur_int_dec() -> None:
    """Editorial amount split: small currency mark + thousands-separated integer +
    decimal tail. No-fraction currencies drop the decimal segment."""
    assert _amount_segments(50000, "CNY") == {"cur": "¥", "int": "500", "dec": ".00"}
    assert _amount_segments(123456, "CNY") == {"cur": "¥", "int": "1,234", "dec": ".56"}
    assert _amount_segments(0, "CNY") == {"cur": "¥", "int": "0", "dec": ".00"}
    assert _amount_segments(None, "CNY") == {"cur": "¥", "int": "0", "dec": ".00"}
    # JPY is a no-fraction currency → dec is empty, amount is the raw minor unit.
    assert _amount_segments(1500, "JPY")["dec"] == ""
    assert _amount_segments(1500, "JPY")["int"] == "1,500"


# ── slice 2a: 详情页 ──────────────────────────────────────────────────────────


def test_web_debt_detail_external_renders_summary(web_client: TestClient, *, identity) -> None:
    debt = _create_external_debt(web_client, identity=identity, direction="i_owe")
    resp = web_client.get(f"/web/debts/{debt['public_id']}")
    assert resp.status_code == 200
    assert "招商信用卡" in resp.text
    assert "应付" in resp.text  # external direction subtitle (businesslike)
    for label in ("本金", "已偿还", "剩余", "未结清"):
        assert label in resp.text
    assert "500.00" in resp.text  # principal row
    # 1B premium: editorial display-split hero + businesslike repayment bar +
    # tracked (letter-spaced) card-title eyebrow (uppercase is a no-op on 剩余).
    assert "dh-amt--hero" in resp.text
    assert "debt-pay-bar" in resp.text
    assert "card-title" in resp.text
    # The duplicate 剩余 ROW is removed (剩余 now lives only in the eyebrow/aria);
    # there must be no 剩余 row label left.
    assert "<span>剩余</span>" not in resp.text


def test_web_debt_detail_member_renders_communal(web_client: TestClient) -> None:
    # Owner viewing their own ledger's member debt → viewer resolves to a party
    # → communal card: 一起处理 eyebrow + relational headline + 看看账, NO accounting
    # framing (应付/应收/剩余) and NO danger tone (red-line ②).
    public_id = _seed_member_debt(direction="i_owe", principal_cents=20000)
    detail = web_client.get(f"/web/debts/{public_id}")
    assert detail.status_code == 200
    assert "一起处理" in detail.text  # participant eyebrow (viewer resolved to a party)
    assert "看看账" in detail.text  # 看看账 expander
    assert "这件事一共" in detail.text  # expander shows total, not remaining
    # Red lines: member detail must not show accounting framing or danger tone.
    assert "应付" not in detail.text
    assert "应收" not in detail.text
    assert "剩余" not in detail.text  # member card never surfaces remaining
    assert "dt-pill danger" not in detail.text  # never red for member debt
    assert "进行中" in detail.text  # member open status badge (neutral)


def test_web_debt_detail_unknown_returns_404(web_client: TestClient) -> None:
    resp = web_client.get("/web/debts/does-not-exist")
    assert resp.status_code == 404


def test_member_headline_matrix() -> None:
    h = _member_headline
    # third-party (viewer_is_debtor=None)
    assert h(None, "open", False, 0.3) == "这件事还在进行中"
    assert h(None, "cleared", False, 1.0) == "这件事，他们已经两清啦"
    assert h(None, "voided", False, 0.0) == "这件事已经不算了"
    # voided wins regardless of party
    assert h(True, "voided", False, 0.5) == "这件事已经不算了"
    # cleared: plain vs forgiven (debtor/creditor)
    assert h(True, "cleared", False, 1.0) == "这件事，我们已经两清啦"
    assert h(True, "cleared", True, 1.0) == "这份 TA 说不用还啦 ❤️"
    assert h(False, "cleared", True, 1.0) == "这份不用补了～"
    # open i_owe (debtor) three tiers + near-ratio boundary (0.7 → near)
    assert h(True, "open", False, 0.0) == "你帮我垫了，慢慢还给你"
    assert h(True, "open", False, 0.3) == "你帮我垫的，正在慢慢对上"
    assert h(True, "open", False, 0.7) == "你帮我垫的，快两清啦"
    # open owed_to_me (creditor) three tiers
    assert h(False, "open", False, 0.0) == "我帮你垫的，不着急"
    assert h(False, "open", False, 0.3) == "我帮你垫的，慢慢来"
    assert h(False, "open", False, 0.9) == "我帮你垫的，快两清啦"


def test_communal_ratio_clamps() -> None:
    assert _communal_ratio(0, 0) == 0.0  # zero principal → 0
    assert _communal_ratio(50, 100) == 0.5
    assert _communal_ratio(200, 100) == 1.0  # clamped high
    assert _communal_ratio(-10, 100) == 0.0  # clamped low


def test_detail_view_member_neutral_and_fx_fallback() -> None:
    # Open member debt → communal card, relational subtitle, status neutral.
    member = _detail_view(
        _stub_debt(counterparty_type="member", counterparty_label="爸爸",
                   viewer_is_debtor=True, status="open", paid_amount_cents=0)
    )
    assert member["is_member"] is True
    assert member["direction_subtitle"] == "你帮我垫的"
    assert member["eyebrow"] == "一起处理 · 爸爸"
    assert member["member_status_tone"] == ""  # open → neutral

    # Voided member debt → neutral, NEVER danger (red-line ②).
    voided = _detail_view(_stub_debt(counterparty_type="member", status="voided"))
    assert voided["is_member"] is True
    assert voided["headline"] == "这件事已经不算了"
    assert voided["member_status_tone"] == ""  # neutral, not danger

    # Foreign-currency member debt → FX fallback to external accounting card.
    foreign = _detail_view(
        _stub_debt(counterparty_type="member", original_currency_code="USD", status="voided")
    )
    assert foreign["is_member"] is False
    assert foreign["status_tone"] == "danger"  # external voided CAN be danger

    # External debt → never member; external voided uses danger tone.
    external = _detail_view(_stub_debt(counterparty_type="external", status="voided"))
    assert external["is_member"] is False
    assert external["status_tone"] == "danger"

    # External card exposes an editorial-split remaining hero + a businesslike
    # paid/principal ratio for the thin neutral repayment bar.
    partial = _detail_view(
        _stub_debt(
            counterparty_type="external", status="open",
            principal_amount_cents=50000, paid_amount_cents=20000,
            remaining_amount_cents=30000,
        )
    )
    assert partial["remaining_segments"] == {"cur": "¥", "int": "300", "dec": ".00"}
    assert partial["paid_ratio_percent"] == 40  # 20000 / 50000
    # Member branch never carries the external accounting fields.
    assert "paid_ratio_percent" not in member
