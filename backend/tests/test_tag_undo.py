"""ADR-0043 tag-mutation undo + purge (契约 2/4/6).

undo single-tx ordered replay (applied/skipped), stale-token 409, per-expense
CAS partial undo, merge→undo round-trip, window expiry → 404, unknown → 404, and
the cleanup purge that frees expired snapshots + keys. Management/CRUD coverage
is in test_tag_management.py.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Tag, TagMutationUndoGroup, TagMutationUndoItem
from app.services.cleanup_service import purge_expired_soft_deletes
from app.services.time_service import now_utc
from tests._infra.tag_helpers import expense_row, manual_expense, tag_index, tag_links


def _delete(client: TestClient, headers: dict[str, str], tag: dict) -> dict:
    return client.post(
        f"/api/tags/{tag['public_id']}/delete",
        headers=headers,
        json={"expected_row_version": tag["row_version"]},
    ).json()


def test_delete_untags_then_undo_restores(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物, 工作", merchant="A")
    a_id, _, _ = expense_row("A")
    tag = tag_index(client, h)["食物"]

    mutation = _delete(client, h, tag)
    assert mutation["op"] == "delete"
    assert mutation["affected_expense_count"] == 1
    assert "食物" not in tag_index(client, h)
    assert tag_links(a_id) == ["工作"]

    undo = client.post(
        f"/api/tags/mutations/{mutation['mutation_public_id']}/undo",
        headers=h,
        json={"expected_row_version": mutation["source_tag_row_version"]},
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["applied"] == 1
    assert "食物" in tag_index(client, h)
    assert tag_links(a_id) == ["工作", "食物"]


def test_undo_stale_tag_token_conflicts(client: TestClient, *, identity) -> None:
    """契约 4 (rev8): an implicit re-create REVIVES the soft-deleted tag (clears
    deleted_at + bumps row_version), so the original delete's token-undo is no
    longer available → 409 (undo step ②'s row_version=token AND deleted_at IS NOT
    NULL predicate fails). The snapshot is kept, not token-undoable after revive."""
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    tag = tag_index(client, h)["食物"]
    mutation = _delete(client, h, tag)
    manual_expense(client, h, tags="食物", merchant="B")  # revives the tag
    undo = client.post(
        f"/api/tags/mutations/{mutation['mutation_public_id']}/undo",
        headers=h,
        json={"expected_row_version": mutation["source_tag_row_version"]},
    )
    assert undo.status_code == 409
    assert undo.json()["error"] == "state_conflict"


def test_undo_partial_skips_edited_expense(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    manual_expense(client, h, tags="食物", merchant="B")
    a_id, _, _ = expense_row("A")
    tag = tag_index(client, h)["食物"]
    mutation = _delete(client, h, tag)

    # Edit A after the delete → its row_version moves past the snapshot CAS token.
    from api_contract_helpers import patch_expense

    patched = patch_expense(client, a_id, headers=h, fields={"merchant": "A2"})
    assert patched.status_code == 200, patched.text

    undo = client.post(
        f"/api/tags/mutations/{mutation['mutation_public_id']}/undo",
        headers=h,
        json={"expected_row_version": mutation["source_tag_row_version"]},
    ).json()
    assert undo["applied"] == 1  # B restored
    assert undo["skipped"] == 1  # A skipped (edited)
    b_id, _, _ = expense_row("B")
    assert tag_links(b_id) == ["食物"]
    assert tag_links(a_id) == []  # A not overwritten


def test_merge_moves_links_dedups_then_undo(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    manual_expense(client, h, tags="食物, 餐饮", merchant="B")
    a_id, _, _ = expense_row("A")
    b_id, _, _ = expense_row("B")
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
    mutation = merged.json()
    assert mutation["op"] == "merge"
    assert "食物" not in tag_index(client, h)
    assert tag_links(a_id) == ["餐饮"]
    assert tag_links(b_id) == ["餐饮"]  # deduped (B already had 餐饮)

    undo = client.post(
        f"/api/tags/mutations/{mutation['mutation_public_id']}/undo",
        headers=h,
        json={"expected_row_version": mutation["source_tag_row_version"]},
    )
    assert undo.status_code == 200, undo.text
    assert "食物" in tag_index(client, h)
    assert tag_links(a_id) == ["食物"]
    assert set(tag_links(b_id)) == {"食物", "餐饮"}


def test_undo_window_expiry_returns_not_found(client: TestClient, *, identity) -> None:
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    tag = tag_index(client, h)["食物"]
    mutation = _delete(client, h, tag)
    with SessionLocal() as db:
        group = db.scalar(
            select(TagMutationUndoGroup).where(
                TagMutationUndoGroup.mutation_public_id == mutation["mutation_public_id"]
            )
        )
        group.created_at = now_utc() - timedelta(minutes=10)
        db.commit()
    undo = client.post(
        f"/api/tags/mutations/{mutation['mutation_public_id']}/undo",
        headers=h,
        json={"expected_row_version": mutation["source_tag_row_version"]},
    )
    assert undo.status_code == 404
    assert undo.json()["error"] == "tag_undo_not_found"


def test_undo_unknown_mutation_not_found(client: TestClient, *, identity) -> None:
    r = client.post(
        "/api/tags/mutations/00000000-0000-0000-0000-000000000000/undo",
        headers=identity.app_headers,
        json={"expected_row_version": 1},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "tag_undo_not_found"


def test_purge_removes_expired_snapshot_keeps_in_window(client: TestClient, *, identity) -> None:
    """契约 6: purge deletes group+items + the still-soft-deleted tag past the
    window (freeing its key), and leaves in-window snapshots untouched."""
    h = identity.app_headers
    manual_expense(client, h, tags="食物", merchant="A")
    manual_expense(client, h, tags="工作", merchant="C")
    expired_tag = tag_index(client, h)["食物"]
    fresh_tag = tag_index(client, h)["工作"]
    expired = _delete(client, h, expired_tag)
    fresh = _delete(client, h, fresh_tag)

    with SessionLocal() as db:
        group = db.scalar(
            select(TagMutationUndoGroup).where(
                TagMutationUndoGroup.mutation_public_id == expired["mutation_public_id"]
            )
        )
        group.created_at = now_utc() - timedelta(minutes=10)
        tag_row = db.scalar(
            select(Tag).where(Tag.tenant_id == "owner").where(Tag.public_id == expired_tag["public_id"])
        )
        tag_row.deleted_at = now_utc() - timedelta(minutes=10)
        expired_group_id = group.id
        db.commit()

    with SessionLocal() as db:
        assert purge_expired_soft_deletes(db) >= 1

    with SessionLocal() as db:
        assert db.scalar(
            select(TagMutationUndoGroup).where(
                TagMutationUndoGroup.mutation_public_id == expired["mutation_public_id"]
            )
        ) is None
        assert db.scalars(
            select(TagMutationUndoItem).where(TagMutationUndoItem.group_id == expired_group_id)
        ).first() is None
        assert db.scalar(select(Tag).where(Tag.tenant_id == "owner").where(Tag.key == "食物")) is None
        assert db.scalar(
            select(TagMutationUndoGroup).where(
                TagMutationUndoGroup.mutation_public_id == fresh["mutation_public_id"]
            )
        ) is not None

    # expired → undo 404 (purged); fresh → undo still works
    assert client.post(
        f"/api/tags/mutations/{expired['mutation_public_id']}/undo",
        headers=h,
        json={"expected_row_version": expired["source_tag_row_version"]},
    ).status_code == 404
    assert client.post(
        f"/api/tags/mutations/{fresh['mutation_public_id']}/undo",
        headers=h,
        json={"expected_row_version": fresh["source_tag_row_version"]},
    ).status_code == 200
