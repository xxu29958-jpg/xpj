"""Shared fixtures for ADR-0049 §6 debt_repayment goal tests.

Split out so the evaluator-semantics and lifecycle-guard suites can stay under
the 500-line file gate (mirrors ``debt_proposal_helpers``).
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Debt,
    DebtAdjustment,
    DebtForgiveness,
    DebtGoalLink,
    Goal,
    LedgerMember,
    Repayment,
    RepaymentVoid,
)

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


def _create_external_debt(
    client: TestClient, headers: dict[str, str], *, principal_amount_cents: int = 10000
) -> dict:
    response = client.post(
        "/api/debts",
        headers=_idem(headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "招商信用卡",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _repay_debt(
    client: TestClient, headers: dict[str, str], debt: dict, *, amount_cents: int
) -> dict:
    """A partial repayment (returns the updated Debt — carries the bumped row_version)."""
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(headers),
        json={"amount_cents": amount_cents, "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _clear_debt(client: TestClient, headers: dict[str, str], debt: dict) -> dict:
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(headers),
        json={
            "amount_cents": debt["principal_amount_cents"],
            "expected_row_version": debt["row_version"],
        },
    )
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "cleared"
    return response.json()


def _void_debt(client: TestClient, headers: dict[str, str], debt: dict) -> dict:
    response = client.post(
        f"/api/debts/{debt['public_id']}/void",
        headers=_idem(headers),
        json={"reason": "重复记录", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "voided"
    return response.json()


def _adjust_debt(
    client: TestClient, headers: dict[str, str], debt: dict, *, amount_cents: int
) -> dict:
    response = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=_idem(headers),
        json={
            "amount_cents": amount_cents,
            "reason": "补记",
            "expected_row_version": debt["row_version"],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _create_debt_goal(
    client: TestClient, headers: dict[str, str], *, name: str, debt_public_ids: list[str]
):
    return client.post(
        "/api/goals",
        headers=headers,
        json={
            "name": name,
            "goal_type": "debt_repayment",
            "debt_public_ids": debt_public_ids,
        },
    )


def _replace_links(
    client: TestClient,
    headers: dict[str, str],
    public_id: str,
    *,
    expected_row_version: int,
    debt_public_ids: list[str],
    idempotency_key: str | None = None,
):
    return client.post(
        f"/api/goals/{public_id}/debt-links",
        headers={**headers, "Idempotency-Key": idempotency_key or str(uuid4())},
        json={"expected_row_version": expected_row_version, "debt_public_ids": debt_public_ids},
    )


def _acknowledge_review(
    client: TestClient,
    headers: dict[str, str],
    public_id: str,
    *,
    expected_row_version: int,
    idempotency_key: str | None = None,
):
    return client.post(
        f"/api/goals/{public_id}/integrity-review/acknowledge",
        headers={**headers, "Idempotency-Key": idempotency_key or str(uuid4())},
        json={"expected_row_version": expected_row_version},
    )


def _goal_latch_state(goal_public_id: str) -> tuple:
    """(achieved_at, achieved_version) read straight from the Goal row.

    Used to prove a read DID or did NOT persist the achievement latch (the
    viewer-read suppression branch can't be observed from the response alone —
    a viewer's computed 'achieved' state still serialises achieved_version=None).
    """
    with SessionLocal() as db:
        goal = db.scalar(select(Goal).where(Goal.public_id == goal_public_id))
        assert goal is not None
        return goal.achieved_at, goal.achieved_version


def _links_count_for_version(goal_public_id: str, version: int) -> int:
    with SessionLocal() as db:
        goal = db.scalar(select(Goal).where(Goal.public_id == goal_public_id))
        assert goal is not None
        return len(
            list(
                db.scalars(
                    select(DebtGoalLink.id).where(
                        DebtGoalLink.goal_id == goal.id,
                        DebtGoalLink.goal_version == version,
                    )
                )
            )
        )


# ── 8e-6b 外部债投影测试支架 ─────────────────────────────────────────────────────────────
# velocity 投影按 fact 的 ``created_at`` 度量观察窗，所以测试要回填 ``created_at`` 到过去并把
# ``now`` 注入评估器才能确定性断言。债 / fact 经真实 API 路径创建（FK / 幂等 / actor 都正确），
# 再 ORM 改写 ``created_at`` 把它们挪到时间窗里；逐测试事务回滚下这些 commit 走 savepoint，
# 测试内对 API 与服务可见、测试后回滚（见 conftest ``_db_isolation``）。


def _backdate_debt_created(debt_public_id: str, created_at: datetime) -> None:
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        debt.created_at = created_at
        db.commit()


def _backdate_latest_repayment(
    debt_public_id: str, created_at: datetime, *, paid_at: datetime | None = None
) -> None:
    """Move the most-recent repayment's ``created_at`` (and optionally ``paid_at``) into the past."""
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        repayment = db.scalar(
            select(Repayment)
            .where(Repayment.debt_id == debt.id)
            .order_by(Repayment.id.desc())
            .limit(1)
        )
        assert repayment is not None
        repayment.created_at = created_at
        if paid_at is not None:
            repayment.paid_at = paid_at
        db.commit()


def _backdate_latest_adjustment(debt_public_id: str, created_at: datetime) -> None:
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        adjustment = db.scalar(
            select(DebtAdjustment)
            .where(DebtAdjustment.debt_id == debt.id)
            .order_by(DebtAdjustment.id.desc())
            .limit(1)
        )
        assert adjustment is not None
        adjustment.created_at = created_at
        db.commit()


def _set_debt_home_currency(debt_public_id: str, home_currency_code: str) -> None:
    """Override a Debt's ``home_currency_code`` (synthetic — the create path always freezes
    the single global home currency, so the mixed-currency suppression guard is exercised
    here by forcing a second currency that production cannot actually produce today)."""
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        debt.home_currency_code = home_currency_code
        db.commit()


def _insert_repayment_fact(
    debt_public_id: str, *, amount_cents: int, created_at: datetime, paid_at: datetime | None = None
) -> None:
    """ORM-insert a ``Repayment`` fact at a controlled ``created_at`` (a member Debt cannot be
    repaid through the direct API — that is the proposal flow — so the gate-biting tests seed
    the fact directly to give a member/mixed plan real paydown the §4 gate must still suppress)."""
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        db.add(
            Repayment(
                debt_id=debt.id,
                amount_cents=amount_cents,
                paid_at=paid_at or created_at,
                actor_account_id=debt.owner_account_id,
                idempotency_key=str(uuid4()),
                created_at=created_at,
            )
        )
        db.commit()


def _void_latest_repayment(debt_public_id: str, *, created_at: datetime) -> None:
    """ORM-insert a ``RepaymentVoid`` for the Debt's most-recent repayment at a controlled
    ``created_at`` (so a repayment counted at the window start but voided DURING the window can
    be exercised — the subtlest fold-as-of branch)."""
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        repayment = db.scalar(
            select(Repayment)
            .where(Repayment.debt_id == debt.id)
            .order_by(Repayment.id.desc())
            .limit(1)
        )
        assert repayment is not None
        db.add(
            RepaymentVoid(
                repayment_id=repayment.id,
                reason="测试作废",
                actor_account_id=debt.owner_account_id,
                idempotency_key=str(uuid4()),
                created_at=created_at,
            )
        )
        db.commit()


def _insert_forgiveness_fact(
    debt_public_id: str, *, amount_cents: int, created_at: datetime
) -> None:
    """ORM-insert a ``DebtForgiveness`` fact (the API blocks forgiveness on external Debt —
    member-only — so the fold's forgiveness term is exercised by inserting the row directly)."""
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        db.add(
            DebtForgiveness(
                debt_id=debt.id,
                amount_cents=amount_cents,
                actor_account_id=debt.owner_account_id,
                idempotency_key=str(uuid4()),
                created_at=created_at,
            )
        )
        db.commit()


def _compute_external_kpi_for(debt_public_ids: list[str], *, now: datetime):
    """Load the named Debts and run the 8e-6b projection with an injected ``now``.

    Returns ``(tracking_days, projected_payoff_date)`` straight from the KPI helper so the
    velocity math can be pinned deterministically."""
    from app.services.goal_debt_repayment_kpi import compute_external_kpi

    with SessionLocal() as db:
        debts = [
            db.scalar(select(Debt).where(Debt.public_id == pid)) for pid in debt_public_ids
        ]
        assert all(debt is not None for debt in debts)
        return compute_external_kpi(db, debts, now=now)
