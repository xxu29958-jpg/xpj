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
    seed_debtor_view,
    seed_external_debt,
    seed_member_debt,
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


def test_web_confirm_stale_old_proposal_keeps_attempt_separate_from_new_pending(
    web_client: TestClient,
) -> None:
    public_id, debt_id, owner_id, member_id, proposal_a = seed_creditor_view()
    before_version = row_version_of(debt_id)
    settled = post_confirm(
        web_client,
        public_id,
        proposal_a,
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD: "80.00",
            "expected_row_version": str(before_version),
        },
    )
    assert settled.status_code == 303
    proposal_b = add_pending_proposal(
        debt_id=debt_id,
        debtor_id=member_id,
        creditor_id=owner_id,
        amount_cents=9_000,
    )

    stale = post_confirm(
        web_client,
        public_id,
        proposal_a,
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD: "50.00",
            "expected_row_version": str(before_version),
        },
    )

    assert stale.status_code == 409
    assert 'role="alert"' in stale.text
    assert f'data-proposal-public-id="{proposal_a}"' in stale.text
    assert "50.00" in stale.text
    assert 'value="50.00"' not in stale.text
    assert f'action="/web/debts/{public_id}/repayment-proposals/{proposal_b}/confirm"' in stale.text
    assert 'value="90.00"' in stale.text
    with SessionLocal() as db:
        old = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_a)
        )
        fresh = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_b)
        )
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
        assert old is not None and old.status == "confirmed"
        assert fresh is not None and fresh.status == "pending"
        assert len(repayments) == 1


# ── P2 构造性旁路：两锚点都不成立时,无锚裸错误块仍须让文案可见 ──────────────


def test_web_confirm_invalid_amount_by_debtor_still_shows_error(
    web_client: TestClient,
) -> None:
    # P2 旁路① (回归)：debtor 直 POST confirm + 非法金额 —— 解析先于服务层 creditor_only
    # 检查,确认表单对 debtor 不渲染、历史兜底又被在途匹配抑制 → 无锚裸块必须仍显示错误,
    # 不得整页无提示 (旧行为 redirect 至少带可见 flash,属退化)。
    public_id, debt_id, _owner_id, _member_id, proposal_public_id = seed_debtor_view()
    before_version = row_version_of(debt_id)

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
    assert "请填写正确的 CNY 金额" in response.text  # 文案可见 (不整页消失)
    assert 'role="alert"' in response.text
    assert f'data-proposal-public-id="{proposal_public_id}"' in response.text
    assert 'aria-invalid="true"' not in response.text  # 无锚:debtor 没有可挂的确认输入
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        assert proposal is not None
        assert proposal.status == "pending"  # 什么都没写
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
        assert repayments == []


def test_web_confirm_invalid_amount_with_forged_proposal_and_no_history_shows_error(
    web_client: TestClient,
) -> None:
    # P2 旁路②：伪造 proposal_public_id + 该债零 proposal 历史 —— 状态/过往区外层条件
    # 不成立 → 错误仍须以无锚裸块显示。
    public_id, debt_id, _owner_id, _member_id = seed_member_debt(direction="owed_to_me")
    before_version = row_version_of(debt_id)

    response = post_confirm(
        web_client,
        public_id,
        "prp_forged000000000000000000000000000",
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD: "abc",
            "expected_row_version": str(before_version),
        },
    )

    assert response.status_code == 422
    assert "请填写正确的 CNY 金额" in response.text
    assert 'role="alert"' in response.text
    with SessionLocal() as db:
        proposals = db.scalars(select(MemberRepaymentProposal).where(MemberRepaymentProposal.debt_id == debt_id)).all()
        assert proposals == []  # 什么都没写 (也没有 proposal 被造出来)
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
        assert repayments == []


def test_web_confirm_invalid_amount_on_external_debt_shows_error(
    web_client: TestClient,
) -> None:
    # P2 旁路③：外部 (非成员) 债 ctx proposals=None —— 两锚都不成立 → 无锚裸块显示错误。
    public_id, debt_id, _owner_id = seed_external_debt()
    before_version = row_version_of(debt_id)

    response = post_confirm(
        web_client,
        public_id,
        "prp_forged000000000000000000000000000",
        **{
            PROPOSAL_CONFIRM_AMOUNT_FIELD: "abc",
            "expected_row_version": str(before_version),
        },
    )

    assert response.status_code == 422
    assert "请填写正确的 CNY 金额" in response.text
    assert 'role="alert"' in response.text
    with SessionLocal() as db:
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
        assert repayments == []
