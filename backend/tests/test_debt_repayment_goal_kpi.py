"""ADR-0049 §7.0 / 8e-6b: the external-debt payoff projection on the evaluation block.

Pins the slice's correctness redlines (the reason 8e-6b is the highest-risk片, not the
cheap one):
 - velocity is the ACTUAL reduction in remaining (signed adjustments / forgiveness folded
   in), NOT a raw repayment sum — a debt knocked down by a write-off is not misjudged;
 - the window is measured on fact ``created_at`` (recording cadence), never the
   user-editable ``paid_at``;
 - projection is suppressed (None) on mixed currency / thin data / no observed paydown;
 - the KPI is server-gated to PURE-EXTERNAL plans (§4) — member / mixed / all-voided
   carry None;
 - "today" is the accounting-tz calendar day, stable across the Asia/Shanghai midnight.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Debt
from app.services.debt_service import compute_remaining, compute_remaining_as_of
from app.services.goal_debt_repayment_kpi import project_payoff_days
from app.services.time_service import now_utc
from tests.debt_proposal_helpers import _create_member_debt, _mint_member_actor
from tests.debt_repayment_goal_helpers import (
    _adjust_debt,
    _backdate_debt_created,
    _backdate_latest_adjustment,
    _backdate_latest_repayment,
    _compute_external_kpi_for,
    _create_debt_goal,
    _create_external_debt,
    _insert_forgiveness_fact,
    _insert_repayment_fact,
    _repay_debt,
    _set_debt_home_currency,
    _void_debt,
    _void_latest_repayment,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _shanghai_payoff(now: datetime, days_left: int) -> date:
    """The payoff date the implementation should produce: accounting-tz today + days_left."""
    return now.astimezone(_SHANGHAI).date() + timedelta(days=days_left)


# ── pure projection math (project_payoff_days) ──────────────────────────────────────────


def test_project_payoff_days_projects_at_observed_pace() -> None:
    # remaining 6000, reduced 4000 over 60d → 66.67/day → ceil(6000 / 66.67) = 90 days.
    assert project_payoff_days(6000, 4000, 60) == 90


def test_project_payoff_days_suppresses_thin_zero_or_no_reduction() -> None:
    assert project_payoff_days(6000, 4000, 13) is None  # window below the 14-day floor
    assert project_payoff_days(0, 4000, 60) is None  # nothing left to pay off
    assert project_payoff_days(6000, 0, 60) is None  # no observed reduction
    assert project_payoff_days(6000, -500, 60) is None  # remaining grew → no projection


# ── compute_remaining_as_of fold (created_at-windowed, every fact type) ─────────────────


def test_remaining_as_of_at_now_equals_full_fold_over_all_fact_types(
    client: TestClient, *, identity
) -> None:
    now = now_utc()
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    after = _repay_debt(client, identity.app_headers, debt, amount_cents=2000)
    _adjust_debt(client, identity.app_headers, after, amount_cents=1000)  # raises remaining
    _insert_forgiveness_fact(debt["public_id"], amount_cents=3000, created_at=now)
    with SessionLocal() as db:
        row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        # principal 10000 + adj 1000 − repay 2000 − forgive 3000 = 6000.
        assert compute_remaining(db, row) == 6000
        # as-of(now) folds every fact type and equals the full fold.
        assert compute_remaining_as_of(db, row, now + timedelta(seconds=1)) == 6000


def test_remaining_as_of_excludes_facts_recorded_after_cutoff(
    client: TestClient, *, identity
) -> None:
    now = now_utc()
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _repay_debt(client, identity.app_headers, debt, amount_cents=4000)
    # the Debt itself existed 60d ago; the repayment was recorded 10d ago.
    _backdate_debt_created(debt["public_id"], now - timedelta(days=60))
    _backdate_latest_repayment(debt["public_id"], now - timedelta(days=10))
    with SessionLocal() as db:
        row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        # cutoff 30d ago is BEFORE the repayment (10d ago) → repayment excluded → principal.
        assert compute_remaining_as_of(db, row, now - timedelta(days=30)) == 10000
        # cutoff 5d ago is AFTER the repayment → counted.
        assert compute_remaining_as_of(db, row, now - timedelta(days=5)) == 6000


def test_remaining_as_of_zero_when_debt_newer_than_cutoff(
    client: TestClient, *, identity
) -> None:
    now = now_utc()
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _backdate_debt_created(debt["public_id"], now - timedelta(days=10))
    with SessionLocal() as db:
        row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        # the Debt did not exist 30d ago → contributes 0 (a debt added mid-window is added
        # remaining, not observed paydown).
        assert compute_remaining_as_of(db, row, now - timedelta(days=30)) == 0


def test_remaining_as_of_excludes_repayment_voided_during_the_window(
    client: TestClient, *, identity
) -> None:
    # The subtlest fold-as-of branch (`RepaymentVoid.created_at <= cutoff`): a repayment recorded
    # BEFORE the cutoff but VOIDED during the window counts at the cutoff (remaining lower then)
    # yet not now (the void restores it), so the window honestly shows remaining going UP →
    # negative reduction → suppressed (never a fake "at risk", §7.0 R4).
    now = now_utc()
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _repay_debt(client, identity.app_headers, debt, amount_cents=4000)
    _backdate_debt_created(debt["public_id"], now - timedelta(days=100))
    _backdate_latest_repayment(debt["public_id"], now - timedelta(days=95))  # before the cutoff
    _void_latest_repayment(debt["public_id"], created_at=now - timedelta(days=10))  # voided in-window
    with SessionLocal() as db:
        row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        # at cutoff −90d: repayment counted (created −95d ≤ −90d), void NOT yet (created −10d) → 6000.
        assert compute_remaining_as_of(db, row, now - timedelta(days=90)) == 6000
        # now: the void excludes the repayment → remaining restored to the full principal.
        assert compute_remaining(db, row) == 10000
    # the projection sees remaining go UP over the window (reduction = 6000 − 10000 < 0) → suppress.
    tracking_days, projected = _compute_external_kpi_for([debt["public_id"]], now=now)
    assert tracking_days is None
    assert projected is None


# ── velocity projection (compute_external_kpi) — the live external scenarios ─────────────


def test_external_projection_from_repayment_pace(client: TestClient, *, identity) -> None:
    now = now_utc()
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _repay_debt(client, identity.app_headers, debt, amount_cents=4000)
    _backdate_debt_created(debt["public_id"], now - timedelta(days=60))
    _backdate_latest_repayment(debt["public_id"], now - timedelta(days=20))
    tracking_days, projected = _compute_external_kpi_for([debt["public_id"]], now=now)
    assert tracking_days == 60
    # remaining 6000, reduced 4000 over 60d → ceil(6000 / (4000/60)) = 90 days out.
    assert projected == _shanghai_payoff(now, 90)


def test_external_projection_counts_writeoff_adjustment_not_just_repayments(
    client: TestClient, *, identity
) -> None:
    # THE blocker (CRITIQUE-1 #1): a debt knocked down only by a NEGATIVE adjustment (a
    # write-off, ZERO repayment rows) must show real downward velocity, not look stalled.
    now = now_utc()
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _adjust_debt(client, identity.app_headers, debt, amount_cents=-4000)  # write-off, no repayment
    _backdate_debt_created(debt["public_id"], now - timedelta(days=60))
    _backdate_latest_adjustment(debt["public_id"], now - timedelta(days=20))
    tracking_days, projected = _compute_external_kpi_for([debt["public_id"]], now=now)
    assert tracking_days == 60
    # same arithmetic as the repayment case: remaining 6000, reduced 4000 over 60d → 90 days.
    assert projected == _shanghai_payoff(now, 90)


def test_external_projection_windows_on_created_at_not_paid_at(
    client: TestClient, *, identity
) -> None:
    # A repayment RECORDED within the window but back-DATED (paid_at far in the past) must
    # still count — velocity is recording cadence (created_at), not the editable paid_at.
    now = now_utc()
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _repay_debt(client, identity.app_headers, debt, amount_cents=4000)
    _backdate_debt_created(debt["public_id"], now - timedelta(days=60))
    _backdate_latest_repayment(
        debt["public_id"], now - timedelta(days=20), paid_at=now - timedelta(days=400)
    )
    tracking_days, projected = _compute_external_kpi_for([debt["public_id"]], now=now)
    assert tracking_days == 60
    assert projected == _shanghai_payoff(now, 90)


def test_external_projection_suppressed_on_mixed_currency(
    client: TestClient, *, identity
) -> None:
    now = now_utc()
    cny = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _repay_debt(client, identity.app_headers, cny, amount_cents=4000)
    _backdate_debt_created(cny["public_id"], now - timedelta(days=60))
    _backdate_latest_repayment(cny["public_id"], now - timedelta(days=20))
    # a second linked Debt in a different home currency makes the remaining sum meaningless.
    usd = _create_external_debt(client, identity.app_headers, principal_amount_cents=5000)
    _backdate_debt_created(usd["public_id"], now - timedelta(days=60))
    _set_debt_home_currency(usd["public_id"], "USD")
    tracking_days, projected = _compute_external_kpi_for(
        [cny["public_id"], usd["public_id"]], now=now
    )
    assert tracking_days is None
    assert projected is None


def test_external_projection_suppressed_on_thin_window(client: TestClient, *, identity) -> None:
    now = now_utc()
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _repay_debt(client, identity.app_headers, debt, amount_cents=4000)
    # plan is only 5 days old → tracking_days < 14 floor → suppress (noisy young rate).
    _backdate_debt_created(debt["public_id"], now - timedelta(days=5))
    _backdate_latest_repayment(debt["public_id"], now - timedelta(days=2))
    tracking_days, projected = _compute_external_kpi_for([debt["public_id"]], now=now)
    assert tracking_days is None
    assert projected is None


def test_external_projection_suppressed_without_paydown(
    client: TestClient, *, identity
) -> None:
    now = now_utc()
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    # 60-day-old plan but no repayment / adjustment at all → zero reduction → no projection.
    _backdate_debt_created(debt["public_id"], now - timedelta(days=60))
    tracking_days, projected = _compute_external_kpi_for([debt["public_id"]], now=now)
    assert tracking_days is None
    assert projected is None


def test_external_projection_uses_accounting_tz_today(client: TestClient, *, identity) -> None:
    # now = 2026-03-01 17:00 UTC = 2026-03-02 01:00 Asia/Shanghai → "today" must be the
    # Shanghai day (03-02), NOT the naive UTC day (03-01) — the midnight off-by-one guard.
    now = datetime(2026, 3, 1, 17, 0, tzinfo=UTC)
    assert now.astimezone(_SHANGHAI).date() != now.date()  # this instant straddles midnight
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _repay_debt(client, identity.app_headers, debt, amount_cents=4000)
    _backdate_debt_created(debt["public_id"], now - timedelta(days=60))
    _backdate_latest_repayment(debt["public_id"], now - timedelta(days=20))
    tracking_days, projected = _compute_external_kpi_for([debt["public_id"]], now=now)
    assert tracking_days == 60
    assert projected == date(2026, 3, 2) + timedelta(days=90)  # Shanghai today + 90
    assert projected != date(2026, 3, 1) + timedelta(days=90)  # not the naive-UTC day


# ── server-side §4 gating: member / mixed / all-voided carry NO projection ──────────────


def test_member_goal_carries_no_projection(client: TestClient, *, identity) -> None:
    now = now_utc()
    member_account_id, _token = _mint_member_actor()
    member = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_account_id
    )
    goal = _create_debt_goal(
        client, identity.app_headers, name="家人", debt_public_ids=[member["public_id"]]
    ).json()
    # bite the §4 gate: give the member debt real aged paydown so that, WITHOUT the gate, the
    # plan WOULD project — proving the None comes from the gate, not from thin data.
    _backdate_debt_created(member["public_id"], now - timedelta(days=60))
    _insert_repayment_fact(member["public_id"], amount_cents=20000, created_at=now - timedelta(days=20))
    detail = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()
    block = detail["debt_repayment"]
    assert block["tracking_days"] is None
    assert block["projected_payoff_date"] is None


def test_mixed_goal_carries_no_projection(client: TestClient, *, identity) -> None:
    now = now_utc()
    member_account_id, _token = _mint_member_actor()
    member = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_account_id
    )
    external = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _repay_debt(client, identity.app_headers, external, amount_cents=4000)
    goal = _create_debt_goal(
        client,
        identity.app_headers,
        name="混装",
        debt_public_ids=[member["public_id"], external["public_id"]],
    ).json()
    # bite the §4 gate: age both debts + the external paydown so that, WITHOUT the gate, the mixed
    # plan WOULD project (single CNY currency, 60d window, positive reduction from the external).
    _backdate_debt_created(member["public_id"], now - timedelta(days=60))
    _backdate_debt_created(external["public_id"], now - timedelta(days=60))
    _backdate_latest_repayment(external["public_id"], now - timedelta(days=20))
    detail = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()
    block = detail["debt_repayment"]
    # one member link makes the plan Mixed (§7.0) — the KPI must NOT appear.
    assert block["tracking_days"] is None
    assert block["projected_payoff_date"] is None


def test_pure_external_goal_carries_projection(client: TestClient, *, identity) -> None:
    now = now_utc()
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    _repay_debt(client, identity.app_headers, debt, amount_cents=4000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="信用卡", debt_public_ids=[debt["public_id"]]
    ).json()
    _backdate_debt_created(debt["public_id"], now - timedelta(days=60))
    _backdate_latest_repayment(debt["public_id"], now - timedelta(days=20))
    detail = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()
    block = detail["debt_repayment"]
    assert block["tracking_days"] == 60
    assert block["projected_payoff_date"] is not None  # populated end-to-end on the wire


def test_all_voided_external_goal_carries_no_projection(
    client: TestClient, *, identity
) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="作废", debt_public_ids=[debt["public_id"]]
    ).json()
    _void_debt(client, identity.app_headers, debt)
    detail = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()
    block = detail["debt_repayment"]
    # every non-voided link gone → not pure-external by the gate → no KPI.
    assert block["tracking_days"] is None
    assert block["projected_payoff_date"] is None
