"""Review P2：金额校验 422 原地重渲染必须锚定到**本次提交**的 proposal。

页面加载后在途 proposal A 被对方处理 (或换了新在途 B) 时,用户仍对 A 提交了非法金额 ——
重渲染按 debt 重新加载,A 已不在途:错误不得随之隐藏,也不得挂到 B 的确认表单上,而是
锚定在 A 沉降进去的 proposal 状态/过往语境 (锚点元素携带 A 的 public_id)。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import MemberRepaymentProposal, Repayment
from app.routes._web_debt_write import PROPOSAL_CONFIRM_AMOUNT_FIELD
from tests._web_debt_proposal_support import (
    add_pending_proposal,
    post_confirm,
    resolve_proposal_out_of_band,
    row_version_of,
    seed_creditor_view,
)

# Uses the shared ``web_client`` fixture (conftest.py) which bypasses the /web loopback
# gate; the loopback web viewer resolves to the ledger owner account.


def test_web_confirm_invalid_amount_after_proposal_resolved_still_anchors_error(
    web_client: TestClient,
) -> None:
    # P2：页面加载后在途 proposal A 被对方处理 (这里=撤回),用户仍对 A 提交了非法金额 →
    # 422 重渲染时 A 已不在途,错误仍渲染且锚定在 A 的语境,不随「当前无在途」而消失。
    public_id, debt_id, _owner_id, member_id, proposal_public_id = seed_creditor_view()
    before_version = row_version_of(debt_id)
    resolve_proposal_out_of_band(proposal_public_id, resolver_account_id=member_id)

    response = post_confirm(
        web_client,
        public_id,
        proposal_public_id,
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD: "abc",
            "expected_row_version": str(before_version),
        },
    )

    assert response.status_code == 422
    assert "请填写正确的 CNY 金额" in response.text  # 错误仍渲染 (不隐藏)
    assert 'role="alert"' in response.text
    # 锚定到被提交的 A (不是别的条目):锚点元素携带 A 的 public_id。
    assert f'data-proposal-public-id="{proposal_public_id}"' in response.text
    assert 'aria-invalid="true"' not in response.text  # 没有在途表单可被错挂
    assert 'value="abc"' not in response.text  # 尝试值不灌进任何现存输入
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        assert proposal is not None
        assert proposal.status == "withdrawn"
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
        assert repayments == []


def test_web_confirm_invalid_amount_error_not_attached_to_new_pending_proposal(
    web_client: TestClient,
) -> None:
    # P2：A 被处理后 B 成为新在途 —— 对 A 的非法提交产生的 422 错误不得挂到 B 的确认表单:
    # B 的输入无 aria-invalid、预填值仍是 B 自己的申报额,错误锚点仍指 A。
    public_id, debt_id, owner_id, member_id, proposal_a = seed_creditor_view()
    before_version = row_version_of(debt_id)
    resolve_proposal_out_of_band(proposal_a, resolver_account_id=member_id)
    proposal_b = add_pending_proposal(
        debt_id=debt_id,
        debtor_id=member_id,
        creditor_id=owner_id,
        amount_cents=6_000,
    )

    response = post_confirm(
        web_client,
        public_id,
        proposal_a,
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD: "abc",
            "expected_row_version": str(before_version),
        },
    )

    assert response.status_code == 422
    assert "请填写正确的 CNY 金额" in response.text
    assert f'data-proposal-public-id="{proposal_a}"' in response.text  # 锚 A
    assert f'data-proposal-public-id="{proposal_b}"' not in response.text  # 不锚 B
    # B 的确认表单照常渲染且干净:动作地址在、无 aria-invalid、预填 B 的申报全额 60.00。
    assert f'action="/web/debts/{public_id}/repayment-proposals/{proposal_b}/confirm"' in response.text
    assert 'aria-invalid="true"' not in response.text
    assert 'value="60.00"' in response.text
    assert 'value="abc"' not in response.text  # A 的尝试值不灌进 B 的输入
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_b)
        )
        assert proposal is not None
        assert proposal.status == "pending"  # B 不受影响
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
        assert repayments == []
