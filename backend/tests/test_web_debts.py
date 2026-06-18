"""/web/debts page (ADR-0049 债务域 web 面 slice 1 — 只读欠款列表)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Debt, LedgerMember
from app.routes.web_debts import _debt_view

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
    assert "500.00" in resp.text  # home-currency principal/remaining


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
    assert "0.00" in resp.text  # remaining is now zero
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


def test_web_debts_lists_member_debt_with_accounting_labels(web_client: TestClient) -> None:
    # The list is a neutral index: member (bill_split) debts render with the SAME
    # accounting direction/status labels as Android DebtListScreen (the relational
    # communal framing is the detail surface's job — a later slice). No
    # counterparty_label → the 家庭成员 fallback. An open member debt is neutral.
    _seed_member_debt(direction="i_owe")
    resp = web_client.get("/web/debts")
    assert resp.status_code == 200
    assert "家庭成员" in resp.text  # counterparty fallback name
    assert "应付" in resp.text  # i_owe direction label (accounting, same as external)
    assert "未结清" in resp.text  # open status label


def _stub_debt(**overrides) -> SimpleNamespace:
    base = {
        "public_id": "dbt_1",
        "counterparty_label": "招商信用卡",
        "counterparty_type": "external",
        "direction": "i_owe",
        "status": "open",
        "remaining_amount_cents": 50000,
        "principal_amount_cents": 50000,
        "home_currency_code": "CNY",
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
