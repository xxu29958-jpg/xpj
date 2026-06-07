"""ADR-0043 tag management contract: list+usage, rename, delete, merge.

Online-only mutate surface — OCC on every op, no Idempotency-Key. Undo / purge
live in test_tag_undo.py. Covers: list usage+orphans, rename mirror-rewrite +
OCC-effective bump + stale-409 + key-collision-409-with-target-token, delete
OCC bump (effective + unrelated untouched) + stale-409, merge dedup +1 +
double-token stale-409 + self-merge-422, read-point soft-delete filters,
viewer-403, ledger isolation, and 401 auth on every route.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import AppError
from app.services.tag_management_service import delete_tag
from tests._infra.tag_helpers import (
    demote_owner_to_viewer,
    expense_row,
    manual_expense,
    occ_claim_blocked,
    tag_index,
    tag_links,
)


def test_list_tags_with_usage_and_orphans(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物, 工作", merchant="A")
    manual_expense(client, h, tags="食物", merchant="B")
    a_id, _, _ = expense_row("A")
    # Orphan: re-tag A to drop 工作 → the 工作 Tag row stays with no links.
    from api_contract_helpers import patch_expense

    patched = patch_expense(client, a_id, headers=h, fields={"tags": "食物"})
    assert patched.status_code == 200, patched.text

    items = tag_index(client, h)
    assert items["食物"]["usage_count"] == 2  # A + B
    assert items["工作"]["usage_count"] == 0  # orphaned
    names_in_order = [it["name"] for it in client.get("/api/tags", headers=h).json()["items"]]
    assert names_in_order.index("食物") < names_in_order.index("工作")  # usage desc


def test_rename_rewrites_mirror_and_bumps_expense(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    a_id, a_ver, _ = expense_row("A")
    tag = tag_index(client, h)["食物"]

    r = client.post(
        f"/api/tags/{tag['public_id']}/rename",
        headers=h,
        json={"expected_row_version": tag["row_version"], "name": "餐饮"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "餐饮"

    assert set(tag_index(client, h)) == {"餐饮"}
    _, _, a_tags = expense_row("A")
    assert a_tags == "餐饮"  # denormalised string rewritten
    assert tag_links(a_id) == ["餐饮"]
    assert occ_claim_blocked(a_id, a_ver)  # expense row_version bumped (OCC-effective)


def test_rename_stale_token_conflicts(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    tag = tag_index(client, h)["食物"]
    r = client.post(
        f"/api/tags/{tag['public_id']}/rename",
        headers=h,
        json={"expected_row_version": tag["row_version"] + 99, "name": "餐饮"},
    )
    assert r.status_code == 409
    assert r.json()["error"] == "state_conflict"


def test_rename_key_collision_returns_target_token(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    manual_expense(client, h, tags="餐饮", merchant="B")
    tags = tag_index(client, h)
    r = client.post(
        f"/api/tags/{tags['食物']['public_id']}/rename",
        headers=h,
        json={"expected_row_version": tags["食物"]["row_version"], "name": "餐饮"},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "tag_conflict"
    assert body["conflict_tag_public_id"] == tags["餐饮"]["public_id"]
    assert body["conflict_tag_row_version"] == tags["餐饮"]["row_version"]


def test_delete_bump_is_occ_effective_and_unrelated_untouched(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    manual_expense(client, h, tags="工作", merchant="B")
    a_id, a_ver, _ = expense_row("A")
    b_id, b_ver, _ = expense_row("B")
    tag = tag_index(client, h)["食物"]

    deleted = client.post(
        f"/api/tags/{tag['public_id']}/delete",
        headers=h,
        json={"expected_row_version": tag["row_version"]},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["affected_expense_count"] == 1
    assert "食物" not in tag_index(client, h)
    assert tag_links(a_id) == []  # untagged
    assert occ_claim_blocked(a_id, a_ver)  # A bumped
    assert not occ_claim_blocked(b_id, b_ver)  # B untouched ("无关账单不 bump")


def test_delete_stale_token_conflicts(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    tag = tag_index(client, h)["食物"]
    r = client.post(
        f"/api/tags/{tag['public_id']}/delete",
        headers=h,
        json={"expected_row_version": tag["row_version"] + 99},
    )
    assert r.status_code == 409
    assert r.json()["error"] == "state_conflict"


def test_merge_stale_tokens_conflict(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    manual_expense(client, h, tags="餐饮", merchant="B")
    tags = tag_index(client, h)
    source_stale = client.post(
        f"/api/tags/{tags['食物']['public_id']}/merge",
        headers=h,
        json={
            "expected_row_version": tags["食物"]["row_version"] + 99,
            "target_public_id": tags["餐饮"]["public_id"],
            "target_row_version": tags["餐饮"]["row_version"],
        },
    )
    assert source_stale.status_code == 409
    target_stale = client.post(
        f"/api/tags/{tags['食物']['public_id']}/merge",
        headers=h,
        json={
            "expected_row_version": tags["食物"]["row_version"],
            "target_public_id": tags["餐饮"]["public_id"],
            "target_row_version": tags["餐饮"]["row_version"] + 99,
        },
    )
    assert target_stale.status_code == 409


def test_merge_dedup_bumps_shared_expense_once(client: TestClient, *, identity) -> None:
    """ADR matrix: merge dedup bumps the shared expense exactly +1 (one OCC
    claim per expense, even when the target link already existed)."""
    h = identity.app_headers
    manual_expense(client, h, tags="食物, 餐饮", merchant="B")  # already has both
    b_id, b_ver, _ = expense_row("B")
    tags = tag_index(client, h)
    merged = client.post(
        f"/api/tags/{tags['食物']['public_id']}/merge",
        headers=h,
        json={
            "expected_row_version": tags["食物"]["row_version"],
            "target_public_id": tags["餐饮"]["public_id"],
            "target_row_version": tags["餐饮"]["row_version"],
        },
    )
    assert merged.status_code == 200, merged.text
    assert tag_links(b_id) == ["餐饮"]  # deduped
    assert occ_claim_blocked(b_id, b_ver)  # bumped...
    assert not occ_claim_blocked(b_id, b_ver + 1)  # ...exactly once (+1, not +2)


def test_merge_soft_deletes_source_even_when_source_has_higher_id(
    client: TestClient, *, identity
) -> None:
    """ADR-0043 review (deadlock fix): the two tag-row claims are now issued in
    ascending tag.id order, but the soft-delete must still land on the SOURCE and
    the bump on the TARGET regardless of which id is lower (set_values stay mapped
    to source/target, not to the claim sequence)."""
    h = identity.app_headers
    manual_expense(client, h, tags="目标", merchant="A")  # created first → lower tag.id
    manual_expense(client, h, tags="来源", merchant="B")  # created second → higher tag.id
    tags = tag_index(client, h)
    r = client.post(
        f"/api/tags/{tags['来源']['public_id']}/merge",  # source has the HIGHER id
        headers=h,
        json={
            "expected_row_version": tags["来源"]["row_version"],
            "target_public_id": tags["目标"]["public_id"],
            "target_row_version": tags["目标"]["row_version"],
        },
    )
    assert r.status_code == 200, r.text
    after = tag_index(client, h)
    assert "来源" not in after  # source soft-deleted (survivor is the target)
    assert "目标" in after
    _, _, b_tags = expense_row("B")
    assert b_tags == "目标"  # B's link moved to the target


def test_delete_tag_require_orphan_rejects_a_relinked_tag(
    client: TestClient, *, identity
) -> None:
    """ADR-0043 review (owner-cleanup TOCTOU): delete_tag(require_orphan=True)
    soft-deletes atomically only while NOT EXISTS(expense_tags). A tag that gained
    a link after the caller's orphan-check (re-tagging doesn't bump row_version,
    so the OCC token can't catch it) is rejected, not clobbered. Service-level —
    the route pre-check would skip first; this pins the atomic backstop."""
    h = identity.app_headers
    manual_expense(client, h, tags="工作", merchant="A")  # 工作 has a live link
    tag = tag_index(client, h)["工作"]
    with SessionLocal() as db, pytest.raises(AppError) as exc:
        delete_tag(
            db,
            tenant_id="owner",
            public_id=tag["public_id"],
            expected_row_version=tag["row_version"],
            require_orphan=True,
        )
    assert exc.value.status_code == 409  # still-live + has a link → state_conflict
    assert "工作" in tag_index(client, h)  # untouched


def test_self_merge_rejected(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    tag = tag_index(client, h)["食物"]
    r = client.post(
        f"/api/tags/{tag['public_id']}/merge",
        headers=h,
        json={
            "expected_row_version": tag["row_version"],
            "target_public_id": tag["public_id"],
            "target_row_version": tag["row_version"],
        },
    )
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request"


def test_soft_deleted_tag_excluded_from_reads(client: TestClient, *, identity) -> None:
    """Read-point deleted_at filters hide a soft-deleted tag even in an
    inconsistent state where its link still exists (defensive — delete normally
    untags first)."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Tag
    from app.services.time_service import now_utc

    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    tag = tag_index(client, h)["食物"]
    with SessionLocal() as db:
        t = db.scalar(
            select(Tag).where(Tag.tenant_id == "owner").where(Tag.public_id == tag["public_id"])
        )
        t.deleted_at = now_utc()
        db.commit()

    filtered = client.get("/api/expenses/confirmed?month=2026-05&tag=食物", headers=h)
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 0  # spending_contract tag filter excludes it
    assert "食物" not in client.get("/api/expenses/tags", headers=h).json()["items"]  # name list
    assert "食物" not in tag_index(client, h)  # management list


def test_viewer_cannot_mutate_tags(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    tag = tag_index(client, h)["食物"]
    demote_owner_to_viewer()
    checks = [
        client.post(f"/api/tags/{tag['public_id']}/rename", headers=h, json={"expected_row_version": tag["row_version"], "name": "餐饮"}),
        client.post(f"/api/tags/{tag['public_id']}/delete", headers=h, json={"expected_row_version": tag["row_version"]}),
        client.post(f"/api/tags/{tag['public_id']}/merge", headers=h, json={"expected_row_version": tag["row_version"], "target_public_id": tag["public_id"], "target_row_version": tag["row_version"]}),
    ]
    for response in checks:
        assert response.status_code == 403, response.text
        assert response.json()["error"] == "permission_denied"


def test_tags_are_ledger_isolated(client: TestClient, *, identity) -> None:
    manual_expense(client, identity.app_headers, tags="食物", merchant="A")
    owner_tag = tag_index(client, identity.app_headers)["食物"]
    cross = client.post(
        f"/api/tags/{owner_tag['public_id']}/delete",
        headers=identity.gray_app_headers,
        json={"expected_row_version": owner_tag["row_version"]},
    )
    assert cross.status_code == 404
    assert cross.json()["error"] == "tag_not_found"


def test_tag_routes_require_auth(client: TestClient) -> None:
    """No bearer token → 401 on every tag route (route-test-matrix gate)."""
    pid = "00000000-0000-0000-0000-000000000000"
    unauthed = [
        client.get("/api/tags"),
        client.post(f"/api/tags/{pid}/rename", json={"expected_row_version": 1, "name": "x"}),
        client.post(f"/api/tags/{pid}/delete", json={"expected_row_version": 1}),
        client.post(
            f"/api/tags/{pid}/merge",
            json={"expected_row_version": 1, "target_public_id": pid, "target_row_version": 1},
        ),
        client.post(f"/api/tags/mutations/{pid}/undo", json={"expected_row_version": 1}),
    ]
    for response in unauthed:
        assert response.status_code == 401, response.text
