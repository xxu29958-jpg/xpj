"""ADR-0049 §6: the debt_repayment goal EVALUATOR semantics.

Pins the §6 contract the goal evaluator owns over the CURRENT version's link set:
``in_progress`` until every linked Debt is cleared (``achieved``, latched once per
version and sticky against a later reopen), unless a linked Debt is voided
(``not_evaluable`` with a review surface, §6 / F13). Changing the linked set bumps
the goal version and freezes the old set's links, so unlinking an open Debt never
retroactively achieves an older version. Lifecycle guards (OCC/idempotency/auth/
isolation) live in ``test_debt_repayment_goal_lifecycle``.

Assertions read the rendered API ``debt_repayment`` block — DB peeks only where a
response can't show per-version link freezing.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.debt_repayment_goal_helpers import (
    _adjust_debt,
    _clear_debt,
    _create_debt_goal,
    _create_external_debt,
    _goal_latch_state,
    _links_count_for_version,
    _replace_links,
    _set_owner_ledger_role,
    _void_debt,
)


def test_create_debt_goal_with_open_debts_is_in_progress(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    b = _create_external_debt(client, identity.app_headers, principal_amount_cents=20000)
    created = _create_debt_goal(
        client, identity.app_headers, name="还清信用卡", debt_public_ids=[a["public_id"], b["public_id"]]
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["goal_type"] == "debt_repayment"
    # spend-shape fields are NULL for a debt goal.
    assert body["month"] is None
    assert body["target_amount_cents"] is None
    assert body["spent_amount_cents"] is None
    assert body["remaining_amount_cents"] is None
    assert body["progress_percent"] is None
    assert body["progress_state"] == "in_progress"
    block = body["debt_repayment"]
    assert block["evaluation_state"] == "in_progress"
    assert block["goal_version"] == 1
    assert block["needs_review"] is False
    assert block["achieved_at"] is None
    assert block["achieved_version"] is None
    assert block["voided_debt_public_ids"] == []
    assert {link["debt_public_id"] for link in block["linked_debts"]} == {a["public_id"], b["public_id"]}
    assert {link["status"] for link in block["linked_debts"]} == {"open"}


def test_all_linked_cleared_achieves_and_latches_once(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    b = _create_external_debt(client, identity.app_headers, principal_amount_cents=20000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="清零", debt_public_ids=[a["public_id"], b["public_id"]]
    ).json()
    _clear_debt(client, identity.app_headers, a)
    _clear_debt(client, identity.app_headers, b)

    detail = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    block = detail.json()["debt_repayment"]
    assert block["evaluation_state"] == "achieved"
    assert block["achieved_version"] == 1
    assert block["achieved_at"] is not None
    assert detail.json()["progress_state"] == "achieved"
    first_achieved_at = block["achieved_at"]

    # Re-read: the latch is sticky and not re-stamped.
    again = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers)
    assert again.json()["debt_repayment"]["achieved_at"] == first_achieved_at
    assert again.json()["debt_repayment"]["achieved_version"] == 1


def test_one_open_debt_keeps_in_progress(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    b = _create_external_debt(client, identity.app_headers, principal_amount_cents=20000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="部分还清", debt_public_ids=[a["public_id"], b["public_id"]]
    ).json()
    _clear_debt(client, identity.app_headers, a)

    detail = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers)
    block = detail.json()["debt_repayment"]
    assert block["evaluation_state"] == "in_progress"
    assert block["achieved_version"] is None
    statuses = {link["debt_public_id"]: link["status"] for link in block["linked_debts"]}
    assert statuses[a["public_id"]] == "cleared"
    assert statuses[b["public_id"]] == "open"


def test_voided_linked_debt_is_not_evaluable_with_review(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    b = _create_external_debt(client, identity.app_headers, principal_amount_cents=20000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="含作废", debt_public_ids=[a["public_id"], b["public_id"]]
    ).json()
    _clear_debt(client, identity.app_headers, a)
    _void_debt(client, identity.app_headers, b)

    detail = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers)
    block = detail.json()["debt_repayment"]
    assert block["evaluation_state"] == "not_evaluable"
    assert block["needs_review"] is True
    assert block["voided_debt_public_ids"] == [b["public_id"]]
    assert block["achieved_version"] is None
    statuses = {link["debt_public_id"]: link["status"] for link in block["linked_debts"]}
    assert statuses[b["public_id"]] == "voided"


def test_replace_links_bumps_version_and_freezes_old_set(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    b = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="改关联", debt_public_ids=[a["public_id"]]
    ).json()
    assert goal["debt_repayment"]["goal_version"] == 1
    assert _links_count_for_version(goal["public_id"], 1) == 1

    replaced = _replace_links(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"],
        debt_public_ids=[a["public_id"], b["public_id"]],
    )
    assert replaced.status_code == 200, replaced.json()
    body = replaced.json()
    assert body["debt_repayment"]["goal_version"] == 2
    assert body["row_version"] == goal["row_version"] + 1
    assert len(body["debt_repayment"]["linked_debts"]) == 2
    # Old version 1's link rows are frozen, not deleted.
    assert _links_count_for_version(goal["public_id"], 1) == 1
    assert _links_count_for_version(goal["public_id"], 2) == 2


def test_unlinking_open_debt_achieves_new_version_not_old(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    b = _create_external_debt(client, identity.app_headers, principal_amount_cents=20000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="解绑未结", debt_public_ids=[a["public_id"], b["public_id"]]
    ).json()
    _clear_debt(client, identity.app_headers, a)  # v1 = {A cleared, B open} → in_progress

    # Drop the still-open B; the new version {A cleared} is achieved — but the
    # achievement belongs to v2, NOT retroactively to v1 (which had B open).
    replaced = _replace_links(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"],
        debt_public_ids=[a["public_id"]],
    )
    assert replaced.status_code == 200, replaced.json()
    block = replaced.json()["debt_repayment"]
    assert block["goal_version"] == 2
    assert block["evaluation_state"] == "achieved"
    assert block["achieved_version"] == 2  # NOT 1 — no retroactive achieve


def test_achieved_then_reopened_debt_stays_achieved(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="重开仍达成", debt_public_ids=[a["public_id"]]
    ).json()
    cleared = _clear_debt(client, identity.app_headers, a)  # carries the post-clear row_version

    achieved = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers)
    assert achieved.json()["debt_repayment"]["evaluation_state"] == "achieved"

    # Reopen the Debt with a positive adjustment (remaining > 0 → status open).
    reopened = _adjust_debt(client, identity.app_headers, cleared, amount_cents=5000)
    assert reopened["status"] == "open"

    detail = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers)
    block = detail.json()["debt_repayment"]
    assert block["evaluation_state"] == "achieved"  # latched per version, sticky
    assert block["achieved_version"] == 1
    assert {link["status"] for link in block["linked_debts"]} == {"open"}


def test_viewer_read_computes_achieved_without_latching(client: TestClient, *, identity) -> None:
    # Writer creates + clears the linked Debt but does NOT read the goal, so the
    # latch is not yet stamped. A viewer's read must COMPUTE 'achieved' but never
    # persist (writer-gated latch). Confirmed both in the response and the DB row.
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="只读不锁存", debt_public_ids=[a["public_id"]]
    ).json()
    _clear_debt(client, identity.app_headers, a)
    assert _goal_latch_state(goal["public_id"]) == (None, None)  # not latched yet

    _set_owner_ledger_role("viewer")
    viewer_read = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers)
    assert viewer_read.status_code == 200, viewer_read.json()
    block = viewer_read.json()["debt_repayment"]
    assert block["evaluation_state"] == "achieved"  # computed
    assert block["achieved_version"] is None  # but not latched
    assert block["achieved_at"] is None
    # The viewer read wrote nothing to the Goal row.
    assert _goal_latch_state(goal["public_id"]) == (None, None)


def test_not_evaluable_recovers_via_link_replace(client: TestClient, *, identity) -> None:
    # §6 / F13: a voided linked Debt is not_evaluable + needs_review, and the user
    # recovers by replacing the link set (dropping the voided Debt) → a new version
    # that re-evaluates cleanly (no lingering needs_review).
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    b = _create_external_debt(client, identity.app_headers, principal_amount_cents=20000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="作废后修复", debt_public_ids=[a["public_id"], b["public_id"]]
    ).json()
    _clear_debt(client, identity.app_headers, a)
    _void_debt(client, identity.app_headers, b)

    blocked = client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers)
    assert blocked.json()["debt_repayment"]["evaluation_state"] == "not_evaluable"

    recovered = _replace_links(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"],
        debt_public_ids=[a["public_id"]],  # drop the voided B
    )
    assert recovered.status_code == 200, recovered.json()
    block = recovered.json()["debt_repayment"]
    assert block["goal_version"] == 2
    assert block["evaluation_state"] == "achieved"  # only the cleared A remains
    assert block["needs_review"] is False
    assert block["voided_debt_public_ids"] == []


def test_debt_goals_listed_separately_from_spending_goals(client: TestClient, *, identity) -> None:
    spending = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={"name": "本月预算", "month": "2026-05", "target_amount_cents": 5000},
    )
    assert spending.status_code == 201, spending.json()
    a = _create_external_debt(client, identity.app_headers)
    debt_goal = _create_debt_goal(
        client, identity.app_headers, name="还债目标", debt_public_ids=[a["public_id"]]
    ).json()

    spending_list = client.get("/api/goals?month=2026-05", headers=identity.app_headers)
    assert [g["name"] for g in spending_list.json()["items"]] == ["本月预算"]

    debt_list = client.get("/api/goals?goal_type=debt_repayment", headers=identity.app_headers)
    assert [g["public_id"] for g in debt_list.json()["items"]] == [debt_goal["public_id"]]
    assert debt_list.json()["items"][0]["goal_type"] == "debt_repayment"


def test_spending_limit_goal_unaffected_by_slice6(client: TestClient, *, identity) -> None:
    created = client.post(
        "/api/goals?timezone=UTC",
        headers=identity.app_headers,
        json={"name": "支出上限", "month": "2026-05", "target_amount_cents": 5000},
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["goal_type"] == "spending_limit"
    # Spend-shape fields stay populated (non-null) and the debt block is absent.
    assert body["target_amount_cents"] == 5000
    assert body["spent_amount_cents"] == 0
    assert body["remaining_amount_cents"] == 5000
    assert body["progress_percent"] == 0
    assert body["progress_state"] == "not_started"
    assert body["debt_repayment"] is None
