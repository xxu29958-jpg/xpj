"""D3：/web/debts/{id}/repayment-proposals/{pid}/confirm 的确认金额表单契约。

模板与路由从同一共享常量 (``PROPOSAL_CONFIRM_AMOUNT_FIELD``) 取字段名——修复前模板提交
``confirmed_amount_major`` 而路由读 ``amount_major``，用户改填的部分金额被静默丢弃，proposal
按对方申报全额入账 (金额事实 bug)。这里钉死：改填值入账 / 留空按全额 (显式分支) / 非法输入
422 原地重渲染且错误锚定到金额输入 / viewer 直 POST 仍 403 / 模板↔路由同源契约。

Review P1 (N-1)：旧字段名 ``amount_major`` 仍被接受 (新字段非空优先，旧字段兜底，两者皆空按
申报全额)——否则旧客户端/旧页面的部分确认会再次静默变成全额；两字段均非空且**不一致** =
客户端序列化/迁移错误 → 422 (不静默取新字段把冲突写成错误金额事实)。P2 的「422 错误锚定到
本次提交的 proposal」在 ``test_web_debt_proposal_confirm_anchor.py``。
"""

from __future__ import annotations

import inspect

from fastapi import params
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.routes.web_debt_proposal_actions as proposal_routes
from app.database import SessionLocal
from app.models import Debt, MemberRepaymentProposal, Repayment
from app.routes._web_debt_write import (
    PROPOSAL_CONFIRM_AMOUNT_FIELD,
    PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY,
)
from app.services.debt_service import get_participant_debt_response
from tests._web_debt_proposal_support import (
    post_confirm,
    proposal_form,
    row_version_of,
    seed_creditor_view,
    viewer_role_only,
)

# Uses the shared ``web_client`` fixture (conftest.py) which bypasses the /web loopback
# gate; the loopback web viewer resolves to the ledger owner account.


def test_web_confirm_with_empty_amount_records_full_declared_amount(
    web_client: TestClient,
) -> None:
    # D3 (b)：留空 = 按对方申报全额确认 (显式分支语义，不是 Form 默认值巧合)。
    public_id, debt_id, owner_id, _member_id, proposal_public_id = seed_creditor_view()
    before_version = row_version_of(debt_id)

    confirmed = web_client.post(
        f"/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm",
        data=proposal_form(
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
    public_id, debt_id, owner_id, _member_id, proposal_public_id = seed_creditor_view()
    before_version = row_version_of(debt_id)
    confirm_url = f"/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm"

    for invalid in ("abc", "-5", "0", "10.005"):
        response = post_confirm(
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

    first = post_confirm(
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
    public_id, debt_id, _owner_id, _member_id, proposal_public_id = seed_creditor_view(currency="JPY")
    before_version = row_version_of(debt_id)

    response = post_confirm(
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
    public_id, debt_id, _owner_id, _member_id, proposal_public_id = seed_creditor_view()
    before_version = row_version_of(debt_id)
    viewer_role_only(monkeypatch)

    response = post_confirm(
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
    # D3 (e) + P1：模板渲染的字段名与路由 Form 绑定必须出自同一共享常量,任一侧漂移都在这里失败。
    signature = inspect.signature(proposal_routes.web_confirm_repayment_proposal)
    form_aliases = {
        parameter.default.alias
        for parameter in signature.parameters.values()
        if isinstance(parameter.default, params.Form)
    }
    assert PROPOSAL_CONFIRM_AMOUNT_FIELD in form_aliases  # 路由绑定共享契约常量 (新名字)
    assert PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY in form_aliases  # N-1 旧名字也出自契约常量
    assert PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY == "amount_major"  # 旧名字冻结 (外部已发布契约)

    public_id, _debt_id, _owner_id, _member_id, proposal_public_id = seed_creditor_view()
    resp = web_client.get(f"/web/debts/{public_id}")
    assert resp.status_code == 200
    assert f'name="{PROPOSAL_CONFIRM_AMOUNT_FIELD}"' in resp.text  # 模板渲染新名字
    # 确认表单内只用新名字 (旧名字不再进确认表单;同页「记一笔还款」等其他表单
    # 仍合法使用 amount_major,故只在确认表单片段内做负断言)。
    confirm_form = resp.text.split(
        f'action="/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm"', 1
    )[1].split("</form>", 1)[0]
    assert f'name="{PROPOSAL_CONFIRM_AMOUNT_FIELD}"' in confirm_form
    assert f'name="{PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY}"' not in confirm_form
    assert 'value="80.00"' in resp.text  # 预填对方申报全额 (留空提交即按全额)


# ── P1：N-1 旧字段 amount_major 兼容 ─────────────────────────────────────────


def test_web_confirm_with_legacy_amount_field_records_edited_partial(
    web_client: TestClient,
) -> None:
    # P1：旧客户端只提交 amount_major (无新字段) 时,改填的部分金额必须按改填值入账——
    # 不得因新字段缺省而退回全额 (这正是 D3 消灭过的静默全额化)。
    public_id, _debt_id, _owner_id, _member_id, proposal_public_id = seed_creditor_view()
    before_version = row_version_of(_debt_id)

    confirmed = web_client.post(
        f"/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm",
        data=proposal_form(
            **{
                PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY: "50.00",
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
        assert proposal.status == "partially_confirmed"
        assert proposal.confirmed_amount_cents == 5_000


def test_web_confirm_conflicting_amount_aliases_rerenders_422_anchored(
    web_client: TestClient,
) -> None:
    # P1/P2：新旧字段同时非空且**不一致** = 客户端序列化/迁移错误 → 422 原地重渲染锚定到
    # 提交的 proposal,零写入 —— 不静默取新字段把冲突写成错误的还款金额事实。
    public_id, debt_id, _owner_id, _member_id, proposal_public_id = seed_creditor_view()
    before_version = row_version_of(debt_id)

    response = post_confirm(
        web_client,
        public_id,
        proposal_public_id,
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD: "50.00",
            PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY: "10.00",
            "expected_row_version": str(before_version),
        },
    )

    assert response.status_code == 422
    assert "两个不一样的金额" in response.text
    assert 'id="proposal-confirm-amount-error"' in response.text  # 仍锚定到金额输入
    assert 'aria-invalid="true"' in response.text
    assert 'value="50.00"' in response.text  # 回填可见输入 (新字段) 的值
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        debt = db.get(Debt, debt_id)
        assert proposal is not None
        assert debt is not None
        assert proposal.status == "pending"  # 零写入
        assert debt.row_version == before_version
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
        assert repayments == []


def test_web_confirm_accepts_matching_amount_aliases(
    web_client: TestClient,
) -> None:
    # P1/P2：新旧字段同时提交但**同值** → 视为单字段提交,按该值入账 (不算冲突)。
    public_id, debt_id, _owner_id, _member_id, proposal_public_id = seed_creditor_view()
    before_version = row_version_of(debt_id)

    confirmed = web_client.post(
        f"/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm",
        data=proposal_form(
            **{
                PROPOSAL_CONFIRM_AMOUNT_FIELD: "50.00",
                PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY: "50.00",
                "expected_row_version": str(before_version),
            }
        ),
    )

    assert confirmed.status_code == 200
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        assert proposal is not None
        assert proposal.status == "partially_confirmed"
        assert proposal.confirmed_amount_cents == 5_000


def test_web_confirm_with_neither_amount_field_records_full_declared_amount(
    web_client: TestClient,
) -> None:
    # P1：两个字段都不提交 → 按对方申报全额 (与留空同一显式分支,不靠 Form 默认值巧合)。
    public_id, debt_id, owner_id, _member_id, proposal_public_id = seed_creditor_view()
    before_version = row_version_of(debt_id)

    confirmed = web_client.post(
        f"/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm",
        data=proposal_form(expected_row_version=str(before_version)),
    )

    assert confirmed.status_code == 200
    assert "收到啦，谢谢 TA" in confirmed.text
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        assert proposal is not None
        assert proposal.status == "confirmed"
        assert proposal.confirmed_amount_cents == 8_000
        fold = get_participant_debt_response(
            db,
            public_id=public_id,
            ledger_id="owner",
            account_id=owner_id,
        )
        assert fold.paid_amount_cents == 8_000
        assert fold.remaining_amount_cents == 12_000


def test_web_confirm_invalid_legacy_amount_rerenders_422_anchored(
    web_client: TestClient,
) -> None:
    # P1：旧字段里的非法值走同一条 422 原地重渲染 + 金额锚定路径,什么都不写。
    public_id, debt_id, _owner_id, _member_id, proposal_public_id = seed_creditor_view()
    before_version = row_version_of(debt_id)

    response = post_confirm(
        web_client,
        public_id,
        proposal_public_id,
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY: "abc",
            "expected_row_version": str(before_version),
        },
    )

    assert response.status_code == 422
    assert "请填写正确的 CNY 金额" in response.text
    assert 'id="proposal-confirm-amount-error"' in response.text
    assert 'aria-invalid="true"' in response.text
    assert 'value="abc"' in response.text  # 旧字段的尝试值同样回填到唯一渲染的输入
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        assert proposal is not None
        assert proposal.status == "pending"
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
        assert repayments == []
