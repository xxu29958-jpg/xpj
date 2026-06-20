"""ADR-0049 §B 完整 installment: contractual schedule + deterministic payoff.

Create stores 期数 × 周期 (paired, installment-kind only); the per-Debt response derives the payoff
date (建账 + count×period months, accounting-tz, day-clamped); an all-installment goal shows that
deterministic date — ``max`` across linked debts — instead of the suppressed velocity projection,
while a mixed / count-less set keeps the §A behavior. Split from test_debt_kind_projection_gate to
keep each file under the 500-line gate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.models import Debt
from app.services.debt_service import installment_payoff_date
from tests.debt_repayment_goal_helpers import (
    _backdate_debt_created,
    _clear_debt,
    _create_debt_goal,
    _create_external_debt,
    _idem,
)


def _get_debt(client: TestClient, headers: dict, public_id: str) -> dict:
    response = client.get(f"/api/debts/{public_id}", headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()


def _payoff_block(client: TestClient, headers: dict, goal_public_id: str) -> dict:
    response = client.get(f"/api/goals/{goal_public_id}", headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()["debt_repayment"]


# ── create + per-Debt response ───────────────────────────────────────────────


def test_create_installment_carries_schedule_and_default_period(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=12
    )
    assert debt["installment_count"] == 12
    # 周期 defaults to 1 (monthly) server-side when count is given and period omitted.
    assert debt["installment_period_months"] == 1
    assert debt["debt_kind"] == "installment"


def test_installment_payoff_date_is_created_plus_count_periods(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment",
        installment_count=4, installment_period_months=3,
    )
    # Anchor 建账 to a fixed accounting-tz date (UTC noon → Asia/Shanghai same date): 2026-01-15
    # + 4×3 = 12 months = 2027-01-15, deterministic and now-independent.
    _backdate_debt_created(debt["public_id"], datetime(2026, 1, 15, 4, 0, tzinfo=UTC))
    fetched = _get_debt(client, identity.app_headers, debt["public_id"])
    assert fetched["installment_period_months"] == 3
    assert fetched["installment_payoff_date"] == "2027-01-15"


def test_installment_payoff_clamps_month_end(client: TestClient, *, identity) -> None:
    # 建账 Jan 31 + 1 month must clamp to Feb 28 (2027 non-leap), never overflow into March.
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=1
    )
    _backdate_debt_created(debt["public_id"], datetime(2027, 1, 31, 4, 0, tzinfo=UTC))
    fetched = _get_debt(client, identity.app_headers, debt["public_id"])
    assert fetched["installment_payoff_date"] == "2027-02-28"


def test_non_installment_debt_has_null_schedule(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity.app_headers, debt_kind="revolving")
    assert debt["installment_count"] is None
    assert debt["installment_period_months"] is None
    assert debt["installment_payoff_date"] is None


def test_create_installment_count_requires_installment_kind(client: TestClient, *, identity) -> None:
    # 期数 on a non-installment kind → 422 (the service's kind-pairing gate, not a silent ignore).
    response = client.post(
        "/api/debts",
        headers=_idem(identity.app_headers),
        json={
            "direction": "i_owe", "counterparty_type": "external", "counterparty_label": "招行",
            "principal_amount_cents": 10000, "debt_kind": "revolving", "installment_count": 6,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"] == "debt_installment_invalid"


def test_create_installment_period_without_count_rejected(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/debts",
        headers=_idem(identity.app_headers),
        json={
            "direction": "i_owe", "counterparty_type": "external", "counterparty_label": "招行",
            "principal_amount_cents": 10000, "debt_kind": "installment", "installment_period_months": 3,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"] == "debt_installment_invalid"


# ── goal-level KPI (deterministic vs suppressed vs velocity) ──────────────────


def test_all_installment_goal_shows_deterministic_payoff(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=6
    )
    _backdate_debt_created(debt["public_id"], datetime(2026, 3, 10, 4, 0, tzinfo=UTC))
    goal = _create_debt_goal(
        client, identity.app_headers, name="分期", debt_public_ids=[debt["public_id"]]
    ).json()
    block = _payoff_block(client, identity.app_headers, goal["public_id"])
    # Deterministic contract payoff (2026-03-10 + 6 months), NOT a velocity guess: no tracking window,
    # no staleness signal.
    assert block["projected_payoff_date"] == "2026-09-10"
    assert block["tracking_days"] is None
    assert block["days_since_last_activity"] is None


def test_all_installment_goal_payoff_is_latest_across_debts(client: TestClient, *, identity) -> None:
    early = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=3
    )
    late = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=12
    )
    _backdate_debt_created(early["public_id"], datetime(2026, 1, 10, 4, 0, tzinfo=UTC))  # → 2026-04-10
    _backdate_debt_created(late["public_id"], datetime(2026, 1, 10, 4, 0, tzinfo=UTC))  # → 2027-01-10
    goal = _create_debt_goal(
        client, identity.app_headers, name="两笔分期",
        debt_public_ids=[early["public_id"], late["public_id"]],
    ).json()
    block = _payoff_block(client, identity.app_headers, goal["public_id"])
    # The plan clears only when the LAST installment finishes → max of the two payoff dates.
    assert block["projected_payoff_date"] == "2027-01-10"


def test_installment_without_count_is_still_suppressed(client: TestClient, *, identity) -> None:
    # debt_kind=installment but NO schedule entered → no deterministic date AND no velocity (it stays
    # in _NO_PROJECTION_KINDS); the goal echoes nothing rather than fabricating a date.
    debt = _create_external_debt(client, identity.app_headers, debt_kind="installment")
    goal = _create_debt_goal(
        client, identity.app_headers, name="未填期数", debt_public_ids=[debt["public_id"]]
    ).json()
    block = _payoff_block(client, identity.app_headers, goal["public_id"])
    assert block["projected_payoff_date"] is None
    assert block["tracking_days"] is None


def test_mixed_installment_and_revolving_is_not_deterministic(client: TestClient, *, identity) -> None:
    # installment(scheduled) + revolving(no paydown) → the set falls to velocity (revolving isn't a
    # no-projection kind), which suppresses on the revolving's zero paydown — so the deterministic
    # installment date is NOT used. Proves the all-installment short-circuit excludes mixed sets.
    inst = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=6
    )
    _backdate_debt_created(inst["public_id"], datetime(2026, 3, 10, 4, 0, tzinfo=UTC))
    rev = _create_external_debt(client, identity.app_headers, debt_kind="revolving")
    goal = _create_debt_goal(
        client, identity.app_headers, name="混装", debt_public_ids=[inst["public_id"], rev["public_id"]]
    ).json()
    block = _payoff_block(client, identity.app_headers, goal["public_id"])
    assert block["projected_payoff_date"] != "2026-09-10"
    assert block["projected_payoff_date"] is None


def test_installment_goal_three_state_vs_target(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=6
    )
    _backdate_debt_created(debt["public_id"], datetime(2026, 3, 10, 4, 0, tzinfo=UTC))  # payoff 2026-09-10
    goal = _create_debt_goal(
        client, identity.app_headers, name="分期", debt_public_ids=[debt["public_id"]],
        target_date="2026-12-31",
    ).json()
    block = _payoff_block(client, identity.app_headers, goal["public_id"])
    # Payoff month (2026-09) earlier than the deadline month (2026-12) → ahead; the deadline echoes.
    assert block["projected_payoff_date"] == "2026-09-10"
    assert block["three_state"] == "ahead"
    assert block["target_date"] == "2026-12-31"


# ── review follow-ups (reclassify gate / settled-suppress / tz anchor / cap) ──


def test_installment_payoff_date_gated_on_debt_kind() -> None:
    # Reclassifying away from installment (set_debt_kind flips only debt_kind, leaving the schedule
    # columns) must make the payoff INERT — a now-revolving debt reports no installment payoff.
    debt = Debt(
        debt_kind="revolving",
        installment_count=6,
        installment_period_months=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert installment_payoff_date(debt) is None
    debt.debt_kind = "installment"
    assert installment_payoff_date(debt) is not None


def test_settled_all_installment_goal_suppresses_payoff(client: TestClient, *, identity) -> None:
    # A fully-repaid all-installment plan must NOT echo a stale contract date — mirror the velocity
    # path's remaining<=0 suppression.
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=6
    )
    _backdate_debt_created(debt["public_id"], datetime(2026, 3, 10, 4, 0, tzinfo=UTC))
    _clear_debt(client, identity.app_headers, debt)  # repay in full → remaining 0
    goal = _create_debt_goal(
        client, identity.app_headers, name="已还清分期", debt_public_ids=[debt["public_id"]]
    ).json()
    block = _payoff_block(client, identity.app_headers, goal["public_id"])
    assert block["projected_payoff_date"] is None


def test_installment_payoff_anchors_on_accounting_tz_date(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=1
    )
    # UTC 16:00 = Asia/Shanghai 00:00 the NEXT calendar day → the schedule must anchor on the
    # Shanghai date (2026-01-16), not the UTC date (2026-01-15). Dropping the tz conversion → 2026-02-15.
    _backdate_debt_created(debt["public_id"], datetime(2026, 1, 15, 16, 0, tzinfo=UTC))
    fetched = _get_debt(client, identity.app_headers, debt["public_id"])
    assert fetched["installment_payoff_date"] == "2026-02-16"


def test_installment_count_over_cap_rejected(client: TestClient, *, identity) -> None:
    # The schema le=600 cap rejects an absurd count BEFORE it can overflow the derived date's year
    # (a self-inflicted 500 otherwise).
    response = client.post(
        "/api/debts",
        headers=_idem(identity.app_headers),
        json={
            "direction": "i_owe", "counterparty_type": "external", "counterparty_label": "招行",
            "principal_amount_cents": 10000, "debt_kind": "installment", "installment_count": 601,
        },
    )
    assert response.status_code == 422
