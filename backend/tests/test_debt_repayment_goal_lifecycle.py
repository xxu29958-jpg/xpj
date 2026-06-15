"""ADR-0049 §6: debt_repayment goal lifecycle GUARDS.

The non-evaluator half of the §6 surface: the link-replace OCC carrier
(idempotent replay / stale-version 409 / required Idempotency-Key / unknown-Debt
404), create-time validation (rejects spend fields / requires ≥1 Debt / unknown
Debt 404), viewer 403, PATCH-rejection (debt goals edit via link-replace only),
archive, and cross-ledger isolation. Evaluator semantics live in
``test_debt_repayment_goal``.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.debt_repayment_goal_helpers import (
    VIEWER_WRITE_MESSAGE,
    _acknowledge_review,
    _clear_debt,
    _create_debt_goal,
    _create_external_debt,
    _links_count_for_version,
    _replace_links,
    _set_owner_ledger_role,
    _void_debt,
)


def test_replace_links_idempotent_replay(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    b = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="幂等改关联", debt_public_ids=[a["public_id"]]
    ).json()
    key = str(uuid4())
    first = _replace_links(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"],
        debt_public_ids=[a["public_id"], b["public_id"]],
        idempotency_key=key,
    )
    assert first.status_code == 200, first.json()
    assert first.json()["debt_repayment"]["goal_version"] == 2

    replay = _replace_links(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"],
        debt_public_ids=[a["public_id"], b["public_id"]],
        idempotency_key=key,
    )
    assert replay.status_code == 200, replay.json()
    # The version did NOT double-bump — the replay returned the canonical result.
    assert replay.json()["debt_repayment"]["goal_version"] == 2
    assert _links_count_for_version(goal["public_id"], 3) == 0


def test_replace_links_stale_version_conflict(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="陈旧版本", debt_public_ids=[a["public_id"]]
    ).json()
    conflict = _replace_links(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"] + 5,
        debt_public_ids=[a["public_id"]],
    )
    assert conflict.status_code == 409, conflict.json()
    assert conflict.json()["error"] == "state_conflict"


def test_replace_links_requires_auth(client: TestClient, *, identity) -> None:
    # coverage: auth-401 — the link-replace carrier rejects an unauthenticated call.
    a = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="未鉴权", debt_public_ids=[a["public_id"]]
    ).json()
    response = client.post(
        f"/api/goals/{goal['public_id']}/debt-links",
        json={"expected_row_version": goal["row_version"], "debt_public_ids": [a["public_id"]]},
    )
    assert response.status_code == 401, response.json()


def test_replace_links_requires_idempotency_key(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="缺幂等键", debt_public_ids=[a["public_id"]]
    ).json()
    response = client.post(
        f"/api/goals/{goal['public_id']}/debt-links",
        headers=identity.app_headers,
        json={"expected_row_version": goal["row_version"], "debt_public_ids": [a["public_id"]]},
    )
    assert response.status_code == 422, response.json()


def test_replace_links_rejects_empty_set(client: TestClient, *, identity) -> None:
    # A debt goal always tracks >=1 Debt — replacing the link set with [] is a
    # schema 422 (DebtGoalLinksReplaceRequest.debt_public_ids min_length=1), with
    # the service _resolve_linked_debts guard as defense-in-depth.
    a = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="不能清空", debt_public_ids=[a["public_id"]]
    ).json()
    response = _replace_links(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"],
        debt_public_ids=[],
    )
    assert response.status_code == 422, response.json()


def test_replace_links_unknown_debt_404(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="未知欠款", debt_public_ids=[a["public_id"]]
    ).json()
    response = _replace_links(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"],
        debt_public_ids=[a["public_id"], str(uuid4())],
    )
    assert response.status_code == 404, response.json()
    assert response.json()["error"] == "debt_not_found"


def test_create_debt_goal_rejects_spending_fields(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    with_month = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": "混入月份",
            "goal_type": "debt_repayment",
            "debt_public_ids": [a["public_id"]],
            "month": "2026-05",
        },
    )
    assert with_month.status_code == 422, with_month.json()
    assert with_month.json()["error"] == "invalid_request"

    with_target = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": "混入金额",
            "goal_type": "debt_repayment",
            "debt_public_ids": [a["public_id"]],
            "target_amount_cents": 1000,
        },
    )
    assert with_target.status_code == 422, with_target.json()


def test_create_debt_goal_requires_at_least_one_debt(client: TestClient, *, identity) -> None:
    empty = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={"name": "空关联", "goal_type": "debt_repayment", "debt_public_ids": []},
    )
    assert empty.status_code == 422, empty.json()

    missing = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={"name": "缺关联", "goal_type": "debt_repayment"},
    )
    assert missing.status_code == 422, missing.json()


def test_create_debt_goal_unknown_debt_404(client: TestClient, *, identity) -> None:
    response = _create_debt_goal(
        client, identity.app_headers, name="不存在的欠款", debt_public_ids=[str(uuid4())]
    )
    assert response.status_code == 404, response.json()
    assert response.json()["error"] == "debt_not_found"


def test_debt_goal_cross_ledger_isolation(client: TestClient, *, identity) -> None:
    gray_debt = _create_external_debt(client, identity.gray_app_headers)
    owner_debt = _create_external_debt(client, identity.app_headers)

    # Owner cannot link a Debt that lives in the gray ledger.
    cross = _create_debt_goal(
        client, identity.app_headers, name="跨账本关联", debt_public_ids=[gray_debt["public_id"]]
    )
    assert cross.status_code == 404, cross.json()
    assert cross.json()["error"] == "debt_not_found"

    owner_goal = _create_debt_goal(
        client, identity.app_headers, name="本账本", debt_public_ids=[owner_debt["public_id"]]
    ).json()
    gray_reads = client.get(
        f"/api/goals/{owner_goal['public_id']}", headers=identity.gray_app_headers
    )
    assert gray_reads.status_code == 404
    assert gray_reads.json()["error"] == "goal_not_found"


def test_viewer_cannot_create_or_replace_debt_goal(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="只读防护", debt_public_ids=[a["public_id"]]
    ).json()

    _set_owner_ledger_role("viewer")
    viewer_create = _create_debt_goal(
        client, identity.app_headers, name="只读建", debt_public_ids=[a["public_id"]]
    )
    assert viewer_create.status_code == 403
    assert viewer_create.json()["error"] == "permission_denied"
    assert viewer_create.json()["message"] == VIEWER_WRITE_MESSAGE

    viewer_replace = _replace_links(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"],
        debt_public_ids=[a["public_id"]],
    )
    assert viewer_replace.status_code == 403
    assert viewer_replace.json()["error"] == "permission_denied"


def test_patch_rejects_debt_goal(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="不能 PATCH", debt_public_ids=[a["public_id"]]
    ).json()
    response = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": goal["row_version"], "name": "改名"},
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "invalid_request"


def test_two_active_debt_goals_coexist(client: TestClient, *, identity) -> None:
    # The scope partial-unique indexes are filtered to spending_limit, so a tenant
    # may keep several active debt_repayment goals at once (item ④ end-to-end).
    a = _create_external_debt(client, identity.app_headers)
    b = _create_external_debt(client, identity.app_headers)
    first = _create_debt_goal(client, identity.app_headers, name="目标一", debt_public_ids=[a["public_id"]])
    second = _create_debt_goal(client, identity.app_headers, name="目标二", debt_public_ids=[b["public_id"]])
    assert first.status_code == 201, first.json()
    assert second.status_code == 201, second.json()


def test_replace_links_rejects_spending_goal(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    spending = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={"name": "支出上限", "month": "2026-05", "target_amount_cents": 5000},
    ).json()
    response = _replace_links(
        client,
        identity.app_headers,
        spending["public_id"],
        expected_row_version=spending["row_version"],
        debt_public_ids=[a["public_id"]],
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "invalid_request"


def _seed_achieved_then_voided_goal(client: TestClient, identity, *, name: str) -> dict:
    """Create a debt goal, latch its achievement, then debt-void the linked Debt.

    Returns the goal create response. The intervening writer GET latches achievement
    BEFORE the void, so the version is sticky-achieved with a pending integrity review
    (the void after the latch does not un-achieve it).
    """
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name=name, debt_public_ids=[a["public_id"]]
    ).json()
    cleared = _clear_debt(client, identity.app_headers, a)
    client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers)  # latch
    _void_debt(client, identity.app_headers, cleared)
    return goal


def test_acknowledge_integrity_review_requires_auth(client: TestClient, *, identity) -> None:
    # coverage: auth-401 — the integrity-review carrier rejects an unauthenticated call.
    a = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="复核未鉴权", debt_public_ids=[a["public_id"]]
    ).json()
    response = client.post(
        f"/api/goals/{goal['public_id']}/integrity-review/acknowledge",
        json={"expected_row_version": goal["row_version"]},
    )
    assert response.status_code == 401, response.json()


def test_acknowledge_integrity_review_requires_idempotency_key(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="复核缺幂等键", debt_public_ids=[a["public_id"]]
    ).json()
    response = client.post(
        f"/api/goals/{goal['public_id']}/integrity-review/acknowledge",
        headers=identity.app_headers,
        json={"expected_row_version": goal["row_version"]},
    )
    assert response.status_code == 422, response.json()


def test_acknowledge_integrity_review_stale_version_conflict(client: TestClient, *, identity) -> None:
    goal = _seed_achieved_then_voided_goal(client, identity, name="复核陈旧版本")
    response = _acknowledge_review(
        client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"] + 5
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "state_conflict"


def test_acknowledge_integrity_review_rejects_not_yet_achieved(client: TestClient, *, identity) -> None:
    # A NOT-yet-achieved version with a voided Debt is not_evaluable — its exit is
    # link-replace (remove the Debt), not the keep-for-audit acknowledge.
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    b = _create_external_debt(client, identity.app_headers, principal_amount_cents=20000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="未达成不能确认", debt_public_ids=[a["public_id"], b["public_id"]]
    ).json()
    _clear_debt(client, identity.app_headers, a)
    _void_debt(client, identity.app_headers, b)  # b never cleared → version never achieved
    response = _acknowledge_review(
        client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"]
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "invalid_request"


def test_acknowledge_integrity_review_idempotent_replay(client: TestClient, *, identity) -> None:
    # ADR-0042 claim-before-OCC: an outbox replay of an ack (same Idempotency-Key +
    # the now-stale expected_row_version) HITs the idempotency table and re-serialises
    # the canonical result — no false-409 on the bumped row_version, no double-apply.
    goal = _seed_achieved_then_voided_goal(client, identity, name="复核幂等重放")
    key = str(uuid4())
    first = _acknowledge_review(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"],
        idempotency_key=key,
    )
    assert first.status_code == 200, first.json()
    assert first.json()["debt_repayment"]["needs_review"] is False

    replay = _acknowledge_review(
        client,
        identity.app_headers,
        goal["public_id"],
        expected_row_version=goal["row_version"],  # now stale, but the HIT short-circuits the OCC
        idempotency_key=key,
    )
    assert replay.status_code == 200, replay.json()
    assert replay.json()["debt_repayment"]["needs_review"] is False


def test_acknowledge_integrity_review_no_pending_review(client: TestClient, *, identity) -> None:
    # A clean achieved goal (no debt-void) has nothing to acknowledge.
    a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        client, identity.app_headers, name="无待复核", debt_public_ids=[a["public_id"]]
    ).json()
    _clear_debt(client, identity.app_headers, a)
    client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers)  # latch achieved
    response = _acknowledge_review(
        client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"]
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "invalid_request"


def test_archive_debt_goal_hides_from_list(client: TestClient, *, identity) -> None:
    a = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(
        client, identity.app_headers, name="可归档", debt_public_ids=[a["public_id"]]
    ).json()
    archived = client.post(
        f"/api/goals/{goal['public_id']}/archive", headers=identity.app_headers
    )
    assert archived.status_code == 200, archived.json()
    assert archived.json()["status"] == "archived"

    active_list = client.get("/api/goals?goal_type=debt_repayment", headers=identity.app_headers)
    assert active_list.json()["items"] == []

    all_list = client.get(
        "/api/goals?goal_type=debt_repayment&include_archived=true", headers=identity.app_headers
    )
    assert [g["public_id"] for g in all_list.json()["items"]] == [goal["public_id"]]
