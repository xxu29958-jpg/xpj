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
from app.services.debt_service import installment_paid_count, installment_payoff_date
from tests.debt_repayment_goal_helpers import (
    _adjust_debt,
    _backdate_debt_created,
    _clear_debt,
    _create_debt_goal,
    _create_external_debt,
    _idem,
    _insert_forgiveness_fact,
    _repay_debt,
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
    assert debt["installment_paid_count"] is None


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


def test_cleared_installment_excluded_from_payoff_max(client: TestClient, *, identity) -> None:
    # Codex P2: an early-repaid installment with a LATER contract date must NOT push the plan payoff
    # out — only OPEN installments (remaining > 0) bound the deterministic max.
    open_debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=3
    )
    cleared_debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=12
    )
    _backdate_debt_created(open_debt["public_id"], datetime(2026, 1, 10, 4, 0, tzinfo=UTC))  # → 2026-04-10
    _backdate_debt_created(cleared_debt["public_id"], datetime(2026, 1, 10, 4, 0, tzinfo=UTC))  # contract → 2027-01-10
    _clear_debt(client, identity.app_headers, cleared_debt)  # fully repaid → remaining 0
    goal = _create_debt_goal(
        client, identity.app_headers, name="一笔已清分期",
        debt_public_ids=[open_debt["public_id"], cleared_debt["public_id"]],
    ).json()
    block = _payoff_block(client, identity.app_headers, goal["public_id"])
    # max over OPEN only → the open debt's 2026-04-10, NOT the cleared debt's later 2027-01-10.
    assert block["projected_payoff_date"] == "2026-04-10"


def test_reclassified_debt_response_hides_schedule_fields(client: TestClient, *, identity) -> None:
    # Codex P2: reclassifying installment→revolving leaves the columns populated (set_debt_kind), but
    # the response must report a clean non-installment shape — ALL schedule fields None, not just payoff.
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=6
    )
    response = client.post(
        f"/api/debts/{debt['public_id']}/kind",
        headers=_idem(identity.app_headers),
        json={"debt_kind": "revolving", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 200, response.json()
    fetched = _get_debt(client, identity.app_headers, debt["public_id"])
    assert fetched["debt_kind"] == "revolving"
    assert fetched["installment_count"] is None
    assert fetched["installment_period_months"] is None
    assert fetched["installment_payoff_date"] is None
    assert fetched["installment_paid_count"] is None


# ── 已还期数 (installment_paid_count, DERIVED from paid) ────────────────────────


def test_installment_paid_count_floors_whole_periods() -> None:
    # per-period = principal // count = 10000 // 4 = 2500; paid 6000 covers 2 whole periods plus a
    # partial one → floor to 2 (a half-paid period does not advance the counter).
    debt = Debt(
        debt_kind="installment", installment_count=4, installment_period_months=1,
        principal_amount_cents=10000,
    )
    assert installment_paid_count(debt, paid=6000) == 2


def test_installment_paid_count_clamps_to_total() -> None:
    # An over-repayment (paid 12500 = 5 periods of 2500) must not report progress beyond the 4 total
    # 期数 — clamp to installment_count.
    debt = Debt(
        debt_kind="installment", installment_count=4, installment_period_months=1,
        principal_amount_cents=10000,
    )
    assert installment_paid_count(debt, paid=12500) == 4


def test_installment_paid_count_gated_on_debt_kind() -> None:
    # Same INERT-after-reclassify gate as the payoff date: a now-revolving debt that still carries the
    # schedule columns reports None, not a stale period count; flipping back to installment revives it.
    debt = Debt(
        debt_kind="revolving", installment_count=4, installment_period_months=1,
        principal_amount_cents=10000,
    )
    assert installment_paid_count(debt, paid=5000) is None
    debt.debt_kind = "installment"
    assert installment_paid_count(debt, paid=5000) == 2


def test_installment_paid_count_degenerate_per_zero_is_zero() -> None:
    # principal < count → per-period floors to 0; guard the divide (a ZeroDivisionError would surface
    # as a 500) and report no whole period rather than crash.
    debt = Debt(
        debt_kind="installment", installment_count=10, installment_period_months=1,
        principal_amount_cents=3,
    )
    assert installment_paid_count(debt, paid=3) == 0


def test_installment_paid_count_in_response_tracks_repayments(client: TestClient, *, identity) -> None:
    # End-to-end: the per-Debt response derives 已还期数 from the FOLDED paid (compute_paid), so a real
    # 5000 repayment on a 10000/4 schedule (per-period 2500) reports 2 periods paid.
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=4,
        principal_amount_cents=10000,
    )
    _repay_debt(client, identity.app_headers, debt, amount_cents=5000)
    fetched = _get_debt(client, identity.app_headers, debt["public_id"])
    assert fetched["installment_paid_count"] == 2


def test_installment_paid_count_forgiveness_does_not_inflate(client: TestClient, *, identity) -> None:
    # 已还期数 is REAL money repaid, not principal-minus-remaining: a forgiveness reduces remaining
    # without cash, so it must NOT advance the counter. Repay 1 period (2500), then forgive 5000 — the
    # count stays 1 (paid 口径), where a remaining-based count would wrongly read 3.
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=4,
        principal_amount_cents=10000,
    )
    _repay_debt(client, identity.app_headers, debt, amount_cents=2500)
    _insert_forgiveness_fact(debt["public_id"], amount_cents=5000, created_at=datetime(2026, 1, 1, tzinfo=UTC))
    fetched = _get_debt(client, identity.app_headers, debt["public_id"])
    assert fetched["installment_paid_count"] == 1


def test_installment_paid_count_ignores_adjustment(client: TestClient, *, identity) -> None:
    # 已还期数 tracks the ORIGINAL contract (principal 10000 / 4 = per-period 2500), NOT the live
    # adjusted obligation — mirroring how the payoff DATE is contract-fixed. A +10000 adjustment raises
    # remaining to 15000, but a 5000 repayment is still 2 of the original installments, not
    # 5000 // ((5000+15000)/4) = 1. Pins the documented adjustment-independence tradeoff.
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=4,
        principal_amount_cents=10000,
    )
    adjusted = _adjust_debt(client, identity.app_headers, debt, amount_cents=10000)
    _repay_debt(client, identity.app_headers, adjusted, amount_cents=5000)
    fetched = _get_debt(client, identity.app_headers, debt["public_id"])
    assert fetched["remaining_amount_cents"] == 15000  # 10000 principal + 10000 adj − 5000 paid
    assert fetched["installment_paid_count"] == 2  # original-contract periods, adjustment ignored


def test_installment_paid_count_installment_kind_without_count_is_none() -> None:
    # The second gate clause: debt_kind=='installment' but NO schedule (installment_count is None) must
    # return None, not crash. Dropping `or installment_count is None` would do `principal // None` →
    # TypeError → 500. The debt_kind-only gate test cannot reach this (it uses revolving WITH a count).
    debt = Debt(
        debt_kind="installment", installment_count=None, installment_period_months=None,
        principal_amount_cents=10000,
    )
    assert installment_paid_count(debt, paid=5000) is None


def test_installment_paid_count_in_repayment_response_body(client: TestClient, *, identity) -> None:
    # The 201 repayment response (RepaymentCreateResponse, a second DebtResponse assembly site) must
    # carry the freshly-folded 已还期数, not just a later GET. Pins the `**debt.model_dump()` spread.
    debt = _create_external_debt(
        client, identity.app_headers, debt_kind="installment", installment_count=4,
        principal_amount_cents=10000,
    )
    body = _repay_debt(client, identity.app_headers, debt, amount_cents=5000)
    assert body["installment_paid_count"] == 2
