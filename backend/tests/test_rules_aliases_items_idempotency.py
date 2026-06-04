"""ADR-0042 Slice D-2: request-idempotency for the rules / aliases / items
mutations (category-rule update+delete, merchant-alias update+delete, items
replace).

Same uniform contract as Slice B's PATCH and Slice D-1's state machine: every
outbox-routed mutate route claims an ``Idempotency-Key`` (via the shared
``claim_idempotent_request``) BEFORE its OCC ``row_version`` claim. Two flavours
of HIT re-serialisation are exercised end-to-end here:

* updates re-serialise the *current* resource (``get_rule_for_tenant`` /
  ``get_merchant_alias`` / ``list_expense_items``) — a committed-but-unseen
  replay with a now-stale token returns canonical state, never the false-409 the
  OCC claim would raise.
* deletes are idempotent by construction — a HIT just returns ``StatusResponse``
  without re-running the soft-delete.

These route tests pin the wiring + the false-409 fix per op; the helper
internals are already covered by Slice B's unit tests.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import ApiIdempotencyKey
from app.schemas import ExpenseItemReplaceRequest
from app.services.idempotency import (
    IDEMPOTENCY_STATUS_IN_PROGRESS,
    fingerprint_request,
)
from app.services.time_service import now_utc

if TYPE_CHECKING:
    from tests._infra.identity import TestIdentity


# ---------------------------------------------------------------------------
# setup helpers — each creates a fresh resource and returns the bits a mutate
# request needs (target id + current row_version).


def _create_rule(client: TestClient, *, identity: TestIdentity, keyword: str = "IdemRuleCafe") -> dict:
    resp = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": keyword, "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_alias(client: TestClient, *, identity: TestIdentity, alias: str = "IDEM 国贸店") -> dict:
    resp = client.post(
        "/api/merchants/aliases",
        headers=identity.app_headers,
        json={"canonical_merchant": "星巴克", "alias": alias},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_items_expense(
    client: TestClient, *, identity: TestIdentity, amount_cents: int = 1500
) -> int:
    """A manual expense (so PUT /items has an editable parent to replace on)."""
    resp = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": amount_cents,
            "merchant": "Idem Items Cafe",
            "category": "餐饮",
            "expense_time": "2026-05-04T01:00:00Z",
        },
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _expense_row_version(client: TestClient, expense_id: int, *, identity: TestIdentity) -> int:
    resp = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["row_version"])


# A request descriptor: (method, url, json-body) with a valid token but NO key.
def _update_rule_request(client: TestClient, *, identity: TestIdentity):
    rule = _create_rule(client, identity=identity)
    return (
        "PATCH",
        f"/api/rules/categories/{rule['id']}",
        {"category": "交通", "expected_row_version": rule["row_version"]},
    )


def _delete_rule_request(client: TestClient, *, identity: TestIdentity):
    rule = _create_rule(client, identity=identity, keyword="IdemRuleDel")
    return (
        "DELETE",
        f"/api/rules/categories/{rule['id']}",
        {"expected_row_version": rule["row_version"]},
    )


def _update_alias_request(client: TestClient, *, identity: TestIdentity):
    alias = _create_alias(client, identity=identity)
    return (
        "PATCH",
        f"/api/merchants/aliases/{alias['public_id']}",
        {"enabled": False, "expected_row_version": alias["row_version"]},
    )


def _delete_alias_request(client: TestClient, *, identity: TestIdentity):
    alias = _create_alias(client, identity=identity, alias="IDEM 删除店")
    return (
        "DELETE",
        f"/api/merchants/aliases/{alias['public_id']}",
        {"expected_row_version": alias["row_version"]},
    )


def _replace_items_request(client: TestClient, *, identity: TestIdentity):
    expense_id = _create_items_expense(client, identity=identity)
    v0 = _expense_row_version(client, expense_id, identity=identity)
    return (
        "PUT",
        f"/api/expenses/{expense_id}/items",
        {
            "expected_row_version": v0,
            "items": [{"name": "拿铁", "amount_cents": 500, "category": "餐饮"}],
        },
    )


_REQUEST_BUILDERS = {
    "update_category_rule": _update_rule_request,
    "delete_category_rule": _delete_rule_request,
    "update_merchant_alias": _update_alias_request,
    "delete_merchant_alias": _delete_alias_request,
    "replace_items": _replace_items_request,
}


# ---------------------------------------------------------------------------
# (a) header-required across all 5 ops


@pytest.mark.parametrize("operation", sorted(_REQUEST_BUILDERS))
def test_mutation_requires_idempotency_key(
    client: TestClient, identity: TestIdentity, operation: str
) -> None:
    """Every outbox-routed rules/aliases/items mutation rejects a keyless
    request with 422 — the missing-key guard runs before the OCC claim, so a
    valid body (fresh token) still 422s ``idempotency_key_required``."""
    method, url, body = _REQUEST_BUILDERS[operation](client, identity=identity)
    resp = client.request(method, url, headers=identity.app_headers, json=body)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == "idempotency_key_required"


# ---------------------------------------------------------------------------
# (b) committed-but-unseen replay → canonical (update_category_rule + replace_items)


def test_update_rule_replay_same_key_returns_canonical_not_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """Committed-but-unseen: the SAME key + SAME now-stale token re-serialises
    the (already-updated) rule rather than the false-409 the OCC claim would
    otherwise raise on the bumped row_version."""
    rule = _create_rule(client, identity=identity)
    v0 = rule["row_version"]
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"category": "交通", "expected_row_version": v0}

    first = client.patch(f"/api/rules/categories/{rule['id']}", headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["category"] == "交通"
    v1 = first.json()["row_version"]
    assert v1 != v0

    replay = client.patch(f"/api/rules/categories/{rule['id']}", headers=headers, json=body)
    assert replay.status_code == 200, replay.text  # HIT, not 409
    assert replay.json()["category"] == "交通"
    assert replay.json()["row_version"] == v1  # canonical, not re-applied


def test_update_rule_stale_token_with_different_key_still_409s(
    client: TestClient, identity: TestIdentity
) -> None:
    """Negative control: a DIFFERENT key with the same now-stale token is a
    genuine concurrent writer → OCC 409 stays intact (idempotency didn't
    weaken OCC)."""
    rule = _create_rule(client, identity=identity)
    v0 = rule["row_version"]
    body = {"category": "交通", "expected_row_version": v0}

    first = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert first.status_code == 200, first.text

    stale = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_replace_items_replay_same_key_returns_canonical_not_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """Committed-but-unseen for the items replace (HIT re-serialises via
    ``list_expense_items`` — a different canonical path than the rule/alias
    ``get_*``): same key + same stale token returns the canonical item list,
    not the false-409 the OCC claim would raise."""
    expense_id = _create_items_expense(client, identity=identity)
    v0 = _expense_row_version(client, expense_id, identity=identity)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {
        "expected_row_version": v0,
        "items": [{"name": "拿铁", "amount_cents": 500, "category": "餐饮"}],
    }

    first = client.put(f"/api/expenses/{expense_id}/items", headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert [item["name"] for item in first.json()["items"]] == ["拿铁"]
    v1 = first.json()["row_version"]
    assert v1 != v0

    replay = client.put(f"/api/expenses/{expense_id}/items", headers=headers, json=body)
    assert replay.status_code == 200, replay.text  # HIT, not 409
    assert [item["name"] for item in replay.json()["items"]] == ["拿铁"]
    assert replay.json()["row_version"] == v1  # canonical, not re-applied


def test_update_alias_replay_same_key_returns_canonical_not_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """Committed-but-unseen for the merchant-alias update — its HIT re-serialises
    via ``get_merchant_alias``, a DISTINCT canonical path from rule-update
    (``get_rule_for_tenant``) and items (``list_expense_items``). Same key + same
    now-stale token returns the canonical (already-updated) alias, not the
    false-409 the OCC claim would raise."""
    alias = _create_alias(client, identity=identity)
    v0 = alias["row_version"]
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"enabled": False, "expected_row_version": v0}

    first = client.patch(
        f"/api/merchants/aliases/{alias['public_id']}", headers=headers, json=body
    )
    assert first.status_code == 200, first.text
    assert first.json()["enabled"] is False
    v1 = first.json()["row_version"]
    assert v1 != v0

    replay = client.patch(
        f"/api/merchants/aliases/{alias['public_id']}", headers=headers, json=body
    )
    assert replay.status_code == 200, replay.text  # HIT via get_merchant_alias, not 409
    assert replay.json()["enabled"] is False
    assert replay.json()["row_version"] == v1  # canonical, not re-applied


# ---------------------------------------------------------------------------
# (c) delete idempotent-replay → 200 StatusResponse via HIT


def test_delete_rule_replay_same_key_returns_ok_via_hit(
    client: TestClient, identity: TestIdentity
) -> None:
    """A delete is idempotent by construction: the first claim soft-deletes the
    rule; a replay with the SAME key + SAME (now-stale) token HITs and returns
    ``StatusResponse`` without re-running the delete or false-409ing."""
    rule = _create_rule(client, identity=identity, keyword="IdemRuleDelHit")
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"expected_row_version": rule["row_version"]}

    first = client.request(
        "DELETE", f"/api/rules/categories/{rule['id']}", headers=headers, json=body
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"status": "ok"}

    replay = client.request(
        "DELETE", f"/api/rules/categories/{rule['id']}", headers=headers, json=body
    )
    assert replay.status_code == 200, replay.text  # HIT, not 409 / not 404
    assert replay.json() == {"status": "ok"}


def test_delete_alias_replay_same_key_returns_ok_via_hit(
    client: TestClient, identity: TestIdentity
) -> None:
    """delete_merchant_alias idempotent-replay (mirrors the rule-delete): the
    first claim soft-deletes the alias; a replay with the SAME key + SAME
    now-stale token HITs and returns ``StatusResponse`` without re-running the
    delete or false-409ing."""
    alias = _create_alias(client, identity=identity, alias="IDEM 删除HIT店")
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"expected_row_version": alias["row_version"]}

    first = client.request(
        "DELETE", f"/api/merchants/aliases/{alias['public_id']}", headers=headers, json=body
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"status": "ok"}

    replay = client.request(
        "DELETE", f"/api/merchants/aliases/{alias['public_id']}", headers=headers, json=body
    )
    assert replay.status_code == 200, replay.text  # HIT, not 409 / not 404
    assert replay.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# (d) in-progress → 409 (hand-built fingerprint matching the route exactly)


def test_update_rule_in_progress_returns_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """A fresh in_progress placeholder (same key + matching fingerprint) blocks
    a concurrent same-key request → 409 idempotency_key_in_progress. The
    fingerprint body is the PATCH's changed fields (``expected_row_version``
    excluded) — exactly what the route computes."""
    rule = _create_rule(client, identity=identity)
    v0 = rule["row_version"]
    key = str(uuid4())
    fingerprint = fingerprint_request(
        operation="update_category_rule",
        target_id=str(rule["id"]),
        body={"category": "交通"},  # model_dump(exclude_unset, exclude expected_row_version)
        expected_row_version=v0,
    )
    with SessionLocal() as db:
        db.add(
            ApiIdempotencyKey(
                tenant_id="owner",
                idempotency_key=key,
                operation="update_category_rule",
                target_type="category_rule",
                target_id=str(rule["id"]),
                request_fingerprint=fingerprint,
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            )
        )
        db.commit()

    resp = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"category": "交通", "expected_row_version": v0},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "idempotency_key_in_progress"


def test_replace_items_in_progress_returns_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """Same in_progress block for the items replace, whose fingerprint body is
    the items list. The body is computed from the SAME request model the route
    parses (``model_dump(mode='json', exclude_unset, exclude
    expected_row_version)``) so the hand-built fingerprint matches exactly."""
    expense_id = _create_items_expense(client, identity=identity)
    v0 = _expense_row_version(client, expense_id, identity=identity)
    items = [{"name": "拿铁", "amount_cents": 500, "category": "餐饮"}]
    key = str(uuid4())
    payload = ExpenseItemReplaceRequest(expected_row_version=v0, items=items)
    fingerprint = fingerprint_request(
        operation="replace_items",
        target_id=str(expense_id),
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=v0,
    )
    with SessionLocal() as db:
        db.add(
            ApiIdempotencyKey(
                tenant_id="owner",
                idempotency_key=key,
                operation="replace_items",
                target_type="expense",
                target_id=str(expense_id),
                request_fingerprint=fingerprint,
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            )
        )
        db.commit()

    resp = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"expected_row_version": v0, "items": items},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "idempotency_key_in_progress"


# ---------------------------------------------------------------------------
# (e) reuse-422 (same key, different request body)


def test_update_rule_same_key_different_body_is_reused_422(
    client: TestClient, identity: TestIdentity
) -> None:
    """§4.7: same key, different request (a different ``category``) → 422
    idempotency_key_reused. The first call succeeded, so the second's
    mismatching fingerprint is rejected before any mutation."""
    rule = _create_rule(client, identity=identity)
    v0 = rule["row_version"]
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}

    first = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers=headers,
        json={"category": "交通", "expected_row_version": v0},
    )
    assert first.status_code == 200, first.text

    reused = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers=headers,
        json={"category": "购物", "expected_row_version": v0},  # different intent
    )
    assert reused.status_code == 422, reused.text
    assert reused.json()["error"] == "idempotency_key_reused"


def test_delete_alias_same_key_different_target_is_reused_422(
    client: TestClient, identity: TestIdentity
) -> None:
    """§4.7 for a delete: replaying the SAME key against a DIFFERENT alias
    (different ``target_id`` → different fingerprint) → 422
    idempotency_key_reused, never silently deleting the wrong row."""
    alias_a = _create_alias(client, identity=identity, alias="IDEM 复用A")
    alias_b = _create_alias(client, identity=identity, alias="IDEM 复用B")
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}

    first = client.request(
        "DELETE",
        f"/api/merchants/aliases/{alias_a['public_id']}",
        headers=headers,
        json={"expected_row_version": alias_a["row_version"]},
    )
    assert first.status_code == 200, first.text

    reused = client.request(
        "DELETE",
        f"/api/merchants/aliases/{alias_b['public_id']}",
        headers=headers,
        json={"expected_row_version": alias_b["row_version"]},
    )
    assert reused.status_code == 422, reused.text
    assert reused.json()["error"] == "idempotency_key_reused"
