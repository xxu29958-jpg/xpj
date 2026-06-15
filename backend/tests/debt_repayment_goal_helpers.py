"""Shared fixtures for ADR-0049 §6 debt_repayment goal tests.

Split out so the evaluator-semantics and lifecycle-guard suites can stay under
the 500-line file gate (mirrors ``debt_proposal_helpers``).
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import DebtGoalLink, Goal, LedgerMember

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
