"""ADR-0049 §7.0 / 8e-6c: the debt_repayment payoff DEADLINE (target_date) + three-state.

Pins: the month-granular three-state (`payoff_three_state`); create-time + setter for the
deadline; the §4 gate (member/mixed carry no three_state); and the critical OCC invariant —
the setter bumps `row_version` but NEVER `goal_version`, so editing a deadline can never
silently un-achieve an achieved goal.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.services.goal_debt_repayment_kpi import payoff_three_state
from app.services.time_service import now_utc
from tests.debt_proposal_helpers import _create_member_debt, _mint_member_actor
from tests.debt_repayment_goal_helpers import (
    VIEWER_WRITE_MESSAGE,
    _backdate_debt_created,
    _backdate_latest_repayment,
    _clear_debt,
    _create_debt_goal,
    _create_external_debt,
    _repay_debt,
    _set_owner_ledger_role,
    _set_target_date,
)

# ── pure three-state math (payoff_three_state) ──────────────────────────────────────────


def test_payoff_three_state_compares_payoff_month_to_deadline_month() -> None:
    assert payoff_three_state(date(2026, 8, 15), date(2026, 9, 1)) == "ahead"  # earlier month
    assert payoff_three_state(date(2026, 10, 1), date(2026, 9, 30)) == "at_risk"  # later month
    assert payoff_three_state(date(2026, 9, 2), date(2026, 9, 28)) == "on_track"  # same month
    assert payoff_three_state(None, date(2026, 9, 1)) is None  # no projection → suppress
    assert payoff_three_state(date(2026, 9, 1), None) is None  # no deadline → suppress


# ── create-time deadline + the §4 gate ─────────────────────────────────────────────────


def _projecting_external_goal(client: TestClient, headers, *, target_date: str | None):
    """A pure-external debt goal with aged paydown (a real projection) + an optional deadline."""
    now = now_utc()
    debt = _create_external_debt(client, headers, principal_amount_cents=10000)
    _repay_debt(client, headers, debt, amount_cents=4000)
    goal = _create_debt_goal(
        client, headers, name="信用卡", debt_public_ids=[debt["public_id"]], target_date=target_date
    ).json()
    _backdate_debt_created(debt["public_id"], now - timedelta(days=60))
    _backdate_latest_repayment(debt["public_id"], now - timedelta(days=20))
    return goal


def test_create_debt_goal_with_target_date_echoes_it(client: TestClient, *, identity) -> None:
    goal = _create_debt_goal(
        client,
        identity.app_headers,
        name="信用卡",
        debt_public_ids=[
            _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)["public_id"]
        ],
        target_date="2027-06-01",
    ).json()
    detail = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()
    assert detail["debt_repayment"]["target_date"] == "2027-06-01"


def test_spending_goal_rejects_target_date(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": "本月餐饮",
            "goal_type": "spending_limit",
            "month": "2026-06",
            "target_amount_cents": 80000,
            "target_date": "2026-12-01",
        },
    )
    assert response.status_code == 422, response.json()


def test_three_state_ahead_when_deadline_is_far_in_the_future(client: TestClient, *, identity) -> None:
    goal = _projecting_external_goal(client, identity.app_headers, target_date="2099-01-01")
    block = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()["debt_repayment"]
    assert block["projected_payoff_date"] is not None
    assert block["target_date"] == "2099-01-01"
    assert block["three_state"] == "ahead"  # any real projection beats a year-2099 deadline


def test_three_state_at_risk_when_deadline_is_in_the_past(client: TestClient, *, identity) -> None:
    goal = _projecting_external_goal(client, identity.app_headers, target_date="2000-01-01")
    block = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()["debt_repayment"]
    # a factual "later than planned" state — the UI renders it amber/warn, never red, no nudge.
    assert block["three_state"] == "at_risk"


def test_three_state_suppressed_without_a_projection(client: TestClient, *, identity) -> None:
    # a deadline but NO observed paydown (thin) → no projection → three_state None (never
    # editorialise "at risk" on missing data); the deadline itself still echoes.
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="信用卡", debt_public_ids=[debt["public_id"]], target_date="2027-01-01"
    ).json()
    block = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()["debt_repayment"]
    assert block["target_date"] == "2027-01-01"
    assert block["projected_payoff_date"] is None
    assert block["three_state"] is None


def test_member_goal_has_no_three_state_even_with_a_deadline(client: TestClient, *, identity) -> None:
    member_account_id, _token = _mint_member_actor()
    member = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_account_id
    )
    goal = _create_debt_goal(
        client, identity.app_headers, name="家人", debt_public_ids=[member["public_id"]], target_date="2027-01-01"
    ).json()
    block = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()["debt_repayment"]
    # §7.0: a member plan is Communal — NO payoff dashboard, even if a deadline was set.
    assert block["target_date"] is None
    assert block["three_state"] is None


# ── the OCC setter route (POST /api/goals/{id}/target-date) ─────────────────────────────


def test_set_target_date_sets_and_clears(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="信用卡", debt_public_ids=[debt["public_id"]]
    ).json()
    set_resp = _set_target_date(
        client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"], target_date="2028-03-01"
    )
    assert set_resp.status_code == 200, set_resp.json()
    assert set_resp.json()["debt_repayment"]["target_date"] == "2028-03-01"
    # clear it (null)
    cleared = _set_target_date(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=set_resp.json()["row_version"],
        target_date=None,
    )
    assert cleared.status_code == 200, cleared.json()
    assert cleared.json()["debt_repayment"]["target_date"] is None


def test_set_target_date_bumps_row_version_not_goal_version(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="信用卡", debt_public_ids=[debt["public_id"]]
    ).json()
    before_goal_version = goal["debt_repayment"]["goal_version"]
    resp = _set_target_date(
        client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"], target_date="2028-03-01"
    ).json()
    assert resp["row_version"] == goal["row_version"] + 1  # OCC token bumped
    assert resp["debt_repayment"]["goal_version"] == before_goal_version  # frozen link set untouched


def test_set_target_date_on_achieved_goal_does_not_unachieve_it(client: TestClient, *, identity) -> None:
    # THE invariant (CRITIQUE-2): bumping goal_version would create an empty version →
    # all_cleared False → silent un-achieve. The setter must bump row_version ONLY.
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _clear_debt(client, identity.app_headers, debt)
    goal = _create_debt_goal(
        client, identity.app_headers, name="清零", debt_public_ids=[debt["public_id"]]
    ).json()
    achieved = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()
    assert achieved["debt_repayment"]["evaluation_state"] == "achieved"
    resp = _set_target_date(
        client, identity.app_headers, goal["public_id"], expected_row_version=achieved["row_version"], target_date="2028-03-01"
    ).json()
    assert resp["debt_repayment"]["evaluation_state"] == "achieved"  # still achieved
    assert resp["debt_repayment"]["achieved_version"] == achieved["debt_repayment"]["achieved_version"]
    assert resp["debt_repayment"]["goal_version"] == achieved["debt_repayment"]["goal_version"]


def test_set_target_date_stale_version_conflict(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="信用卡", debt_public_ids=[debt["public_id"]]
    ).json()
    response = _set_target_date(
        client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"] + 99, target_date="2028-03-01"
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "state_conflict"


def test_set_target_date_requires_auth(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="信用卡", debt_public_ids=[debt["public_id"]]
    ).json()
    response = client.post(
        f"/api/goals/{goal['public_id']}/target-date",
        json={"expected_row_version": goal["row_version"], "target_date": "2028-03-01"},
    )
    assert response.status_code == 401, response.json()


def test_set_target_date_viewer_forbidden(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="信用卡", debt_public_ids=[debt["public_id"]]
    ).json()
    _set_owner_ledger_role("viewer")
    response = _set_target_date(
        client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"], target_date="2028-03-01"
    )
    assert response.status_code == 403, response.json()
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_set_target_date_idempotent_replay(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="信用卡", debt_public_ids=[debt["public_id"]]
    ).json()
    key = "set-target-date-once"
    first = _set_target_date(
        client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"], target_date="2028-03-01", idempotency_key=key
    ).json()
    replay = _set_target_date(
        client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"], target_date="2028-03-01", idempotency_key=key
    ).json()
    # the replay re-serialises the same goal (same row_version) — not a second bump.
    assert replay["row_version"] == first["row_version"]
    assert replay["debt_repayment"]["target_date"] == "2028-03-01"
