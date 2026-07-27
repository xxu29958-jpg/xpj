"""D3：/web/debts/{id}/repayment-proposals/{pid}/confirm 的确认金额表单契约。

模板与路由从同一共享常量 (``PROPOSAL_CONFIRM_AMOUNT_FIELD``) 取字段名——修复前模板提交
``confirmed_amount_major`` 而路由读 ``amount_major``，用户改填的部分金额被静默丢弃，proposal
按对方申报全额入账 (金额事实 bug)。这里钉死：改填值入账 / 留空按全额 (显式分支) / 非法输入
422 原地重渲染且错误锚定到金额输入 / viewer 直 POST 仍 403 / 模板↔路由同源契约。
"""

from __future__ import annotations

import inspect
from datetime import timedelta
from uuid import uuid4

from fastapi import params
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.routes.web_debt_proposal_actions as proposal_routes
from app.database import SessionLocal
from app.models import Account, Debt, LedgerMember, MemberRepaymentProposal, Repayment
from app.routes._web_debt_write import PROPOSAL_CONFIRM_AMOUNT_FIELD
from app.routes.web_common import LedgerOption
from app.services.debt_service import get_participant_debt_response
from app.services.time_service import now_utc

# Uses the shared ``web_client`` fixture (conftest.py) which bypasses the /web loopback
# gate; the loopback web viewer resolves to the ledger owner account.


def _owner_account_id(db) -> int:
    owner_account_id = db.scalar(
        select(LedgerMember.account_id).where(LedgerMember.ledger_id == "owner", LedgerMember.role == "owner").limit(1)
    )
    assert owner_account_id is not None
    return owner_account_id


def _seed_creditor_view(*, currency: str = "CNY") -> tuple[str, int, int, int, str]:
    """Seed an 'owed_to_me' member debt + one pending proposal from the family member;
    the loopback web viewer (owner) is the creditor who can confirm. Returns
    (debt_public_id, debt_id, owner_id, member_id, proposal_public_id)."""
    with SessionLocal() as db:
        member = Account(display_name="家人")
        db.add(member)
        db.flush()
        owner_account_id = _owner_account_id(db)
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_account_id,
            created_by_account_id=owner_account_id,
            direction="owed_to_me",
            counterparty_type="member",
            counterparty_account_id=member.id,
            principal_amount_cents=20000,
            home_currency_code=currency,
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.flush()
        created = now_utc()
        proposal = MemberRepaymentProposal(
            debt_id=debt.id,
            debtor_account_id=member.id,
            creditor_account_id=owner_account_id,
            proposed_by_account_id=member.id,
            proposed_amount_cents=8_000,
            home_currency_code=currency,
            paid_at=created,
            status="pending",
            created_at=created,
            expires_at=created + timedelta(days=30),
            idempotency_key=str(uuid4()),
        )
        db.add(proposal)
        db.commit()
        return debt.public_id, debt.id, owner_account_id, member.id, proposal.public_id


def _row_version(debt_id: int) -> int:
    with SessionLocal() as db:
        debt = db.get(Debt, debt_id)
        assert debt is not None
        return debt.row_version


def _proposal_form(**values: str) -> dict[str, str]:
    return {
        "csrf_token": "test-client-bypasses-middleware-check",
        "ledger_id": "owner",
        "idempotency_key": str(uuid4()),
        **values,
    }


def _post_confirm(web_client: TestClient, debt_public_id: str, proposal_public_id: str, **values: str):
    return web_client.post(
        f"/web/debts/{debt_public_id}/repayment-proposals/{proposal_public_id}/confirm",
        data=_proposal_form(**values),
        follow_redirects=False,
    )


def _viewer_role(monkeypatch) -> None:
    """Force the selected ledger option to role=viewer (只读角色路径)。"""
    monkeypatch.setattr(
        proposal_routes,
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


def test_web_confirm_with_empty_amount_records_full_declared_amount(
    web_client: TestClient,
) -> None:
    # D3 (b)：留空 = 按对方申报全额确认 (显式分支语义，不是 Form 默认值巧合)。
    public_id, debt_id, owner_id, _member_id, proposal_public_id = _seed_creditor_view()
    before_version = _row_version(debt_id)

    confirmed = web_client.post(
        f"/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm",
        data=_proposal_form(
            **{
                PROPOSAL_CONFIRM_AMOUNT_FIELD: "",
                "expected_row_version": str(before_version),
            }
        ),
    )

    assert confirmed.status_code == 200
    assert "收到啦，谢谢 TA" in confirmed.text
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        assert proposal is not None
        assert proposal.status == "confirmed"  # 全额两清,非 partially_confirmed
        assert proposal.confirmed_amount_cents == 8_000
        fold = get_participant_debt_response(
            db,
            public_id=public_id,
            ledger_id="owner",
            account_id=owner_id,
        )
        assert fold.paid_amount_cents == 8_000
        assert fold.remaining_amount_cents == 12_000


def test_web_confirm_invalid_amount_rerenders_422_anchored_and_writes_nothing(
    web_client: TestClient,
) -> None:
    # D3 (c)：非法金额输入 (非数字 / 负数 / 零 / 超精度) → 422 原地重渲染,
    # 错误锚定到确认金额输入 (role=alert + aria-invalid + aria-describedby),什么都不写。
    public_id, debt_id, owner_id, _member_id, proposal_public_id = _seed_creditor_view()
    before_version = _row_version(debt_id)
    confirm_url = f"/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm"

    for invalid in ("abc", "-5", "0", "10.005"):
        response = _post_confirm(
            web_client,
            public_id,
            proposal_public_id,
            **{
                PROPOSAL_CONFIRM_AMOUNT_FIELD: invalid,
                "expected_row_version": str(before_version),
            },
        )
        assert response.status_code == 422
        assert 'id="proposal-confirm-amount-error"' in response.text  # 锚定到金额输入
        assert 'role="alert"' in response.text
        assert 'aria-invalid="true"' in response.text
        assert 'aria-describedby="proposal-confirm-amount-error"' in response.text
        # 原地重渲染:确认表单还在 (同页),立即可改填重试。
        assert f'action="{confirm_url}"' in response.text
        assert f'name="{PROPOSAL_CONFIRM_AMOUNT_FIELD}"' in response.text

    first = _post_confirm(
        web_client,
        public_id,
        proposal_public_id,
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD: "abc",
            "expected_row_version": str(before_version),
        },
    )
    assert first.status_code == 422
    assert "请填写正确的 CNY 金额" in first.text
    assert 'value="abc"' in first.text  # 错误后回填刚才的尝试值,不让用户猜

    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        debt = db.get(Debt, debt_id)
        assert proposal is not None
        assert debt is not None
        assert proposal.status == "pending"  # 什么都没写
        assert proposal.confirmed_amount_cents is None
        assert debt.row_version == before_version
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
        assert repayments == []
        fold = get_participant_debt_response(
            db,
            public_id=public_id,
            ledger_id="owner",
            account_id=owner_id,
        )
        assert fold.paid_amount_cents == 0


def test_web_confirm_rejects_over_precise_zero_decimal_currency_input(
    web_client: TestClient,
) -> None:
    # D3 (c) 边界:JPY/KRW 零小数币种,带小数的确认金额同样 422 锚定重渲染 (复用共享解析闸门)。
    public_id, _debt_id, _owner_id, _member_id, proposal_public_id = _seed_creditor_view(currency="JPY")
    before_version = _row_version(_debt_id)

    response = _post_confirm(
        web_client,
        public_id,
        proposal_public_id,
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD: "5000.5",
            "expected_row_version": str(before_version),
        },
    )

    assert response.status_code == 422
    assert "JPY 金额只能填写整数。" in response.text
    assert 'aria-describedby="proposal-confirm-amount-error"' in response.text
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        assert proposal is not None
        assert proposal.status == "pending"


def test_web_confirm_direct_post_as_viewer_is_rejected(
    web_client: TestClient,
    monkeypatch,
) -> None:
    # D3 (d)：viewer 直接 POST 仍被 403 拒绝 (写门禁在金额解析之前,什么都不写)。
    public_id, debt_id, _owner_id, _member_id, proposal_public_id = _seed_creditor_view()
    before_version = _row_version(debt_id)
    _viewer_role(monkeypatch)

    response = _post_confirm(
        web_client,
        public_id,
        proposal_public_id,
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD: "50.00",
            "expected_row_version": str(before_version),
        },
    )

    assert response.status_code == 403
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        assert proposal is not None
        assert proposal.status == "pending"
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
        assert repayments == []


def test_confirm_amount_field_contract_binds_template_and_route(web_client: TestClient) -> None:
    # D3 (e)：模板渲染的字段名与路由 Form 绑定必须出自同一共享常量,任一侧漂移都在这里失败。
    signature = inspect.signature(proposal_routes.web_confirm_repayment_proposal)
    form_aliases = {
        parameter.default.alias
        for parameter in signature.parameters.values()
        if isinstance(parameter.default, params.Form)
    }
    assert PROPOSAL_CONFIRM_AMOUNT_FIELD in form_aliases  # 路由绑定共享契约常量
    assert "amount_major" not in form_aliases  # 确认端不再读申报字段名 (D3 根因)

    public_id, _debt_id, _owner_id, _member_id, _proposal_public_id = _seed_creditor_view()
    resp = web_client.get(f"/web/debts/{public_id}")
    assert resp.status_code == 200
    assert f'name="{PROPOSAL_CONFIRM_AMOUNT_FIELD}"' in resp.text  # 模板从同一常量渲染
    assert 'value="80.00"' in resp.text  # 预填对方申报全额 (留空提交即按全额)
