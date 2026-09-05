"""Web adapter contract for external/manual Debt fact commands."""

from __future__ import annotations

import re
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.routes.web_debt_actions as web_debt_action_routes
import app.routes.web_debt_create as web_debt_create_routes
import app.routes.web_debts as web_debts_routes
import app.services.debt_command_service as debt_command_service
from app.database import SessionLocal
from app.models import Account, Debt, LedgerMember, Repayment
from app.services.spending_contract_service import accounting_zone


def test_web_debt_fact_adapters_delegate_to_shared_commands_and_views() -> None:
    assert web_debt_action_routes.record_repayment_idempotently is debt_command_service.record_repayment_idempotently
    assert web_debt_create_routes.create_debt_idempotently is debt_command_service.create_debt_idempotently
    assert web_debt_create_routes._debt_create_context is web_debts_routes._debt_create_context


def _headers(identity) -> dict[str, str]:
    return {**identity.app_headers, "Idempotency-Key": str(uuid4())}


def _create_debt(
    web_client: TestClient,
    *,
    identity,
    principal_amount_cents: int = 50_000,
) -> dict:
    response = web_client.post(
        "/api/debts",
        headers=_headers(identity),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "测试信用卡",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _form(
    debt: dict,
    *,
    idempotency_key: str,
    **values: str,
) -> dict[str, str]:
    return {
        "csrf_token": "test-client-bypasses-middleware-check",
        "ledger_id": "owner",
        "expected_row_version": str(debt["row_version"]),
        "idempotency_key": idempotency_key,
        **values,
    }


def _detail(web_client: TestClient, *, identity, public_id: str) -> dict:
    response = web_client.get(
        f"/api/debts/{public_id}",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_member_debt_for_owner_creditor() -> str:
    with SessionLocal() as db:
        owner_account_id = db.scalar(
            select(LedgerMember.account_id)
            .where(LedgerMember.ledger_id == "owner")
            .order_by(LedgerMember.id.asc())
            .limit(1)
        )
        assert owner_account_id is not None
        debtor = Account(display_name="家庭成员")
        db.add(debtor)
        db.flush()
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_account_id,
            created_by_account_id=owner_account_id,
            direction="owed_to_me",
            counterparty_type="member",
            counterparty_account_id=debtor.id,
            principal_amount_cents=12_000,
            home_currency_code="CNY",
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.commit()
        return debt.public_id


def test_web_repayment_replay_is_idempotent(
    web_client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_debt(web_client, identity=identity)
    page = web_client.get(f"/web/debts/{debt['public_id']}?ledger_id=owner")
    assert page.status_code == 200
    assert 'data-body-stack="product"' in page.text
    assert "/static/web/product/domains/obligations.css" in page.text
    assert "/static/web/pages/debts.css" not in page.text
    assert 'style="' not in page.text
    assert 'name="amount_major"' in page.text
    assert f'action="/web/debts/{debt["public_id"]}/forgive"' not in page.text
    assert "本次还款（CNY · ¥，最多两位小数）" in page.text
    assert 'min="0.01"' in page.text
    assert 'step="0.01"' in page.text
    key = str(uuid4())
    form = _form(
        debt,
        idempotency_key=key,
        amount_major="120.50",
        paid_at="2026-07-18",
    )

    first = web_client.post(
        f"/web/debts/{debt['public_id']}/repayments",
        data=form,
    )
    replay = web_client.post(
        f"/web/debts/{debt['public_id']}/repayments",
        data=form,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert 'id="debt-action-feedback"' in first.text
    assert 'id="debt-action-feedback"' in replay.text
    assert "还款事实已记录" in first.text
    assert "还款事实已记录" in replay.text
    current = _detail(web_client, identity=identity, public_id=debt["public_id"])
    assert current["paid_amount_cents"] == 12_050
    assert current["remaining_amount_cents"] == 37_950
    assert current["row_version"] == debt["row_version"] + 1
    with SessionLocal() as db:
        paid_at = db.scalar(
            select(Repayment.paid_at)
            .join(Debt, Debt.id == Repayment.debt_id)
            .where(Debt.public_id == debt["public_id"])
        )
    assert paid_at is not None
    assert paid_at.astimezone(accounting_zone()).date().isoformat() == "2026-07-18"


def test_web_adjustment_appends_signed_fact_without_rewriting_principal(
    web_client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_debt(web_client, identity=identity)
    response = web_client.post(
        f"/web/debts/{debt['public_id']}/adjustments",
        data=_form(
            debt,
            idempotency_key=str(uuid4()),
            amount_major="-50.00",
            reason="减免手续费",
        ),
    )

    assert response.status_code == 200
    assert "本金调整事实已记录" in response.text
    current = _detail(web_client, identity=identity, public_id=debt["public_id"])
    assert current["principal_amount_cents"] == 50_000
    assert current["remaining_amount_cents"] == 45_000
    assert current["row_version"] == debt["row_version"] + 1


def test_web_void_appends_fact_and_closes_direct_actions(
    web_client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_debt(web_client, identity=identity)
    response = web_client.post(
        f"/web/debts/{debt['public_id']}/void",
        data=_form(
            debt,
            idempotency_key=str(uuid4()),
            reason="重复建账",
        ),
    )

    assert response.status_code == 200
    assert "原始事实仍保留" in response.text
    assert f"/web/debts/{debt['public_id']}/repayments" not in response.text
    current = _detail(web_client, identity=identity, public_id=debt["public_id"])
    assert current["status"] == "voided"
    assert current["row_version"] == debt["row_version"] + 1


def test_web_stale_row_version_surfaces_conflict_without_second_fact(
    web_client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_debt(web_client, identity=identity)
    api_repayment = web_client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_headers(identity),
        json={
            "amount_cents": 1_000,
            "expected_row_version": debt["row_version"],
        },
    )
    assert api_repayment.status_code == 201, api_repayment.text

    stale = web_client.post(
        f"/web/debts/{debt['public_id']}/repayments",
        data=_form(
            debt,
            idempotency_key=str(uuid4()),
            amount_major="20.00",
            paid_at="2026-07-19",
        ),
    )

    assert stale.status_code == 409
    assert 'id="debt-action-error-repayment"' in stale.text
    assert "另一端刚更新了这笔欠款" in stale.text
    assert 'value="20.00"' in stale.text
    assert 'value="2026-07-19"' in stale.text
    assert f'name="expected_row_version" value="{debt["row_version"] + 1}"' in stale.text
    current = _detail(web_client, identity=identity, public_id=debt["public_id"])
    assert current["paid_amount_cents"] == 1_000
    assert current["row_version"] == debt["row_version"] + 1


def test_web_viewer_hides_and_cannot_post_direct_commands(
    web_client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_debt(web_client, identity=identity)
    with SessionLocal() as db:
        membership = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").order_by(LedgerMember.id.asc()).limit(1)
        )
        assert membership is not None
        membership.role = "viewer"
        db.commit()

    page = web_client.get(f"/web/debts/{debt['public_id']}?ledger_id=owner")
    assert page.status_code == 200
    assert f"/web/debts/{debt['public_id']}/repayments" not in page.text
    assert "当前角色可查看欠款事实" in page.text
    assert web_client.get("/web/debts/new?ledger_id=owner").status_code == 403

    denied = web_client.post(
        f"/web/debts/{debt['public_id']}/repayments",
        data=_form(
            debt,
            idempotency_key=str(uuid4()),
            amount_major="10.00",
        ),
    )
    assert denied.status_code == 403
    assert denied.json()["error"] == "permission_denied"
    assert (
        _detail(
            web_client,
            identity=identity,
            public_id=debt["public_id"],
        )["paid_amount_cents"]
        == 0
    )


def test_web_external_debt_create_is_complete_and_idempotent(
    web_client: TestClient,
    *,
    identity,
) -> None:
    page = web_client.get("/web/debts/new?ledger_id=owner")
    assert page.status_code == 200
    assert 'action="/web/debts"' in page.text
    assert 'name="direction"' in page.text
    assert 'name="currency_code"' in page.text
    assert 'name="event_time"' in page.text
    assert 'name="debt_kind"' in page.text
    assert "服务端按发生日冻结汇率" in page.text

    key = str(uuid4())
    expected_note = "出差垫款 <行程说明>\n".ljust(500, "事")
    form = {
        "csrf_token": "test-client-bypasses-middleware-check",
        "ledger_id": "owner",
        "direction": "i_owe",
        "counterparty_label": "Web 完整建账",
        "amount_major": "321.45",
        "currency_code": "CNY",
        "event_time": "2026-07-18T09:30",
        "debt_kind": "installment",
        "installment_count": "12",
        "installment_period_months": "1",
        "note": expected_note.replace("\n", "\r\n"),
        "idempotency_key": key,
    }
    first = web_client.post("/web/debts", data=form)
    replay = web_client.post("/web/debts", data={**form, "note": expected_note})

    assert first.status_code == 200
    assert replay.status_code == 200
    assert "Web 完整建账" in first.text
    assert "分期还款" in first.text
    assert "出差垫款 &lt;行程说明&gt;" in first.text
    assert "出差垫款 &lt;行程说明&gt;" in replay.text
    with SessionLocal() as db:
        rows = db.scalars(
            select(Debt).where(
                Debt.tenant_id == "owner",
                Debt.counterparty_label == "Web 完整建账",
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].principal_amount_cents == 32_145
        assert rows[0].installment_count == 12
        public_id = rows[0].public_id
    current = _detail(web_client, identity=identity, public_id=public_id)
    assert current["note"] == expected_note
    changed = web_client.post("/web/debts", data={**form, "note": "不同的往来缘由"})
    assert changed.status_code == 422
    assert _detail(web_client, identity=identity, public_id=public_id)["note"] == expected_note


def test_web_external_debt_create_validation_preserves_fields(
    web_client: TestClient,
) -> None:
    response = web_client.post(
        "/web/debts",
        data={
            "csrf_token": "test-client-bypasses-middleware-check",
            "ledger_id": "owner",
            "direction": "i_owe",
            "counterparty_label": "日元借款",
            "amount_major": "12.50",
            "currency_code": "JPY",
            "event_time": "2026-07-18T09:30",
            "debt_kind": "one_off",
            "note": "一起出差垫的交通费",
            "idempotency_key": str(uuid4()),
        },
    )

    assert response.status_code == 422
    assert "日元借款" in response.text
    assert "一起出差垫的交通费" in response.text
    assert 'value="12.50"' in response.text
    assert "金额" in response.text
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(Debt.id).where(
                    Debt.tenant_id == "owner",
                    Debt.counterparty_label == "日元借款",
                )
            )
            is None
        )


def test_web_debt_kind_and_repayment_void_restore_canonical_fold(
    web_client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_debt(
        web_client,
        identity=identity,
        principal_amount_cents=10_000,
    )
    kind = web_client.post(
        f"/web/debts/{debt['public_id']}/kind",
        data=_form(
            debt,
            idempotency_key=str(uuid4()),
            debt_kind="one_off",
        ),
    )
    assert kind.status_code == 200
    assert "还款类型已更新" in kind.text
    assert re.search(
        r'<option(?=[^>]*\bvalue="one_off")(?=[^>]*\bselected\b)[^>]*>',
        kind.text,
    )
    classified = _detail(
        web_client,
        identity=identity,
        public_id=debt["public_id"],
    )
    assert classified["debt_kind"] == "one_off"

    repayment = web_client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_headers(identity),
        json={
            "amount_cents": 10_000,
            "expected_row_version": classified["row_version"],
        },
    )
    assert repayment.status_code == 201, repayment.text
    cleared = repayment.json()
    page = web_client.get(f"/web/debts/{debt['public_id']}?ledger_id=owner")
    assert page.status_code == 200
    assert "还款记录" in page.text
    assert "已生效" in page.text
    assert "撤销这笔误记" in page.text

    undone = web_client.post(
        f"/web/debts/{debt['public_id']}/repayment-voids",
        data=_form(
            cleared,
            idempotency_key=str(uuid4()),
            repayment_public_id=cleared["repayment_public_id"],
            reason="重复记了一次",
        ),
    )
    assert undone.status_code == 200
    assert "误记还款已撤销" in undone.text
    assert "已撤销" in undone.text
    current = _detail(
        web_client,
        identity=identity,
        public_id=debt["public_id"],
    )
    assert current["status"] == "open"
    assert current["paid_amount_cents"] == 0
    assert current["remaining_amount_cents"] == 10_000


def test_web_member_creditor_can_forgive_remaining(
    web_client: TestClient,
    *,
    identity,
) -> None:
    public_id = _seed_member_debt_for_owner_creditor()
    page = web_client.get(f"/web/debts/{public_id}?ledger_id=owner")
    assert page.status_code == 200
    assert f'action="/web/debts/{public_id}/repayments"' not in page.text
    assert f'action="/web/debts/{public_id}/adjustments"' not in page.text
    assert f'action="/web/debts/{public_id}/kind"' not in page.text
    assert f'action="/web/debts/{public_id}/void"' not in page.text
    assert f"/web/debts/{public_id}/forgive" in page.text
    assert "免除这笔往来" in page.text
    assert "免除剩余往来" not in page.text  # 红线②:成员卡不出现会计框

    current = _detail(web_client, identity=identity, public_id=public_id)
    forgiven = web_client.post(
        f"/web/debts/{public_id}/forgive",
        data=_form(
            current,
            idempotency_key=str(uuid4()),
        ),
    )
    assert forgiven.status_code == 200
    assert "对方无需再还" in forgiven.text
    result = _detail(web_client, identity=identity, public_id=public_id)
    assert result["status"] == "cleared"
    assert result["is_forgiven"] is True
    assert result["remaining_amount_cents"] == 0
