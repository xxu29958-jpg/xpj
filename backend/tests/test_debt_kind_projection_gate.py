"""ADR-0049 §7.0 / 8e-6e: ``debt_kind`` gates the external-debt payoff projection.

A no-rhythm kind (``one_off`` IOU / ``installment`` contractual schedule) makes the velocity
projection lie (no cadence / decreasing pace, payoff is contractual not extrapolated), so an
all-no-rhythm external plan suppresses it. A mixed set with ≥1 ``revolving`` / ``unspecified``
Debt still projects over the whole set (the aggregate paydown is meaningful; ``unspecified``
keeps current behavior). The suppressed bundle still echoes a user-set deadline.

Split from ``test_debt_repayment_goal_kpi`` to keep that file under the 500-line gate (mirrors
the proposal/web-debts test splits). Goes through the wire (``GET /api/goals/{id}`` → evaluator
→ the GATED ``external_payoff_kpi``), since the helper ``_compute_external_kpi_for`` calls the
ungated ``compute_external_kpi`` directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.services.time_service import now_utc
from tests.debt_repayment_goal_helpers import (
    _backdate_debt_created,
    _backdate_latest_repayment,
    _create_debt_goal,
    _create_external_debt,
    _repay_debt,
)


def _aged_external_debt(client: TestClient, identity, now: datetime, *, debt_kind: str) -> dict:
    """An external Debt of ``debt_kind`` with a 60-day window + a 20-day-old repayment — the
    SAME aging as test_pure_external_goal_carries_projection (which DOES project for an
    unspecified Debt), so a suppressed projection proves the KIND gate, not thin data."""
    debt = _create_external_debt(
        client, identity.app_headers, principal_amount_cents=10000, debt_kind=debt_kind
    )
    _repay_debt(client, identity.app_headers, debt, amount_cents=4000)
    _backdate_debt_created(debt["public_id"], now - timedelta(days=60))
    _backdate_latest_repayment(debt["public_id"], now - timedelta(days=20))
    return debt


def test_external_goal_all_one_off_suppresses_projection(
    client: TestClient, *, identity
) -> None:
    now = now_utc()
    debt = _aged_external_debt(client, identity, now, debt_kind="one_off")
    goal = _create_debt_goal(
        client, identity.app_headers, name="借款", debt_public_ids=[debt["public_id"]]
    ).json()
    block = client.get(
        f"/api/goals/{goal['public_id']}", headers=identity.app_headers
    ).json()["debt_repayment"]
    # 8e-6e: a one-time IOU has no cadence → no velocity projection (None here vs a real date
    # in test_pure_external_goal_carries_projection under identical aging = the kind gate bit).
    assert block["projected_payoff_date"] is None
    assert block["tracking_days"] is None
    assert block["days_since_last_activity"] is None
    assert block["three_state"] is None


def test_external_goal_all_installment_suppresses_projection(
    client: TestClient, *, identity
) -> None:
    now = now_utc()
    debt = _aged_external_debt(client, identity, now, debt_kind="installment")
    goal = _create_debt_goal(
        client, identity.app_headers, name="分期", debt_public_ids=[debt["public_id"]]
    ).json()
    block = client.get(
        f"/api/goals/{goal['public_id']}", headers=identity.app_headers
    ).json()["debt_repayment"]
    # installment decreases on a contractual schedule → linear velocity over-projects; suppress
    # (its payoff is the contract's 期数×周期, addressed by the later full-installment slice).
    assert block["projected_payoff_date"] is None
    assert block["tracking_days"] is None


def test_external_goal_mixed_kinds_still_projects(client: TestClient, *, identity) -> None:
    now = now_utc()
    one_off = _create_external_debt(
        client, identity.app_headers, principal_amount_cents=10000, debt_kind="one_off"
    )
    revolving = _aged_external_debt(client, identity, now, debt_kind="revolving")
    _backdate_debt_created(one_off["public_id"], now - timedelta(days=60))
    goal = _create_debt_goal(
        client,
        identity.app_headers,
        name="混装",
        debt_public_ids=[one_off["public_id"], revolving["public_id"]],
    ).json()
    block = client.get(
        f"/api/goals/{goal['public_id']}", headers=identity.app_headers
    ).json()["debt_repayment"]
    # 8e-6e: a set with ≥1 revolving/unspecified Debt still projects over the WHOLE set (the
    # aggregate paydown is meaningful; "project some, not others" is incoherent) — NOT suppressed.
    assert block["projected_payoff_date"] is not None
    assert block["tracking_days"] is not None


def test_suppressed_external_goal_still_echoes_target_date(
    client: TestClient, *, identity
) -> None:
    now = now_utc()
    debt = _aged_external_debt(client, identity, now, debt_kind="one_off")
    goal = _create_debt_goal(
        client,
        identity.app_headers,
        name="借款",
        debt_public_ids=[debt["public_id"]],
        target_date="2027-01-31",
    ).json()
    block = client.get(
        f"/api/goals/{goal['public_id']}", headers=identity.app_headers
    ).json()["debt_repayment"]
    # 8e-6e: the projection is suppressed for the kind, but the user-set deadline is a fact they
    # entered — still echo it (three_state stays None: no projection to compare it against).
    assert block["projected_payoff_date"] is None
    assert block["three_state"] is None
    assert block["target_date"] == "2027-01-31"
