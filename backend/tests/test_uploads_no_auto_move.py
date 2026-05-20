"""v0.3.1-alpha2 Phase 2 — uploads migration / rollback consistency.

These tests pin down the conservative policy required by the v0.3.1-alpha2
contract:

* ``init_db`` MUST NOT silently move legacy ``uploads/YYYY/MM/...`` files into
  ``uploads/<tenant>/YYYY/MM/...`` on startup. The opt-in helper
  ``migrate_upload_paths_to_tenant_dirs`` is still available for scripts.
* ``resolve_protected_image`` MUST keep working for legacy paths that have not
  been migrated, while rejecting absolute paths, Windows drive specs, and
  ``..`` traversal attempts.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import BACKEND_ROOT, SessionLocal, init_db
from app.models import Expense
from api_contract_helpers import upload_png
from tests._infra.env import TEST_UPLOAD_DIR
from tests._infra.assets import PNG_BYTES
def test_init_db_does_not_move_legacy_uploads(client: TestClient) -> None:
    """Pre-existing legacy ``uploads/YYYY/MM/foo.png`` files must stay put
    after ``init_db`` runs again. Re-running init_db is what start-up does.
    """

    legacy_dir = TEST_UPLOAD_DIR / "2026" / "05"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_image = legacy_dir / "stay-here.png"
    legacy_image.write_bytes(PNG_BYTES)
    legacy_relative = legacy_image.relative_to(BACKEND_ROOT).as_posix()

    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            image_path=legacy_relative,
            image_hash="legacy-stay-hash",
            status="pending",
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        expense_id = expense.id

    # Re-run init_db (this is what backend startup does on every boot).
    init_db()

    # Legacy file MUST still be at the original path. No tenant-prefixed copy
    # should have been created either.
    assert legacy_image.is_file()
    tenant_copy = (
        TEST_UPLOAD_DIR / "owner" / "2026" / "05" / "stay-here.png"
    )
    assert not tenant_copy.exists()

    with SessionLocal() as db:
        refreshed = db.get(Expense, expense_id)
        assert refreshed is not None
        assert refreshed.image_path == legacy_relative


def test_protected_image_route_serves_legacy_path_without_migration(
    client: TestClient, *, identity,
) -> None:
    """A pre-v0.3 expense whose ``image_path`` still has no tenant prefix must
    be readable by the owning tenant after the route has verified ownership.
    The image file must NOT have to be moved first.
    """

    legacy_dir = TEST_UPLOAD_DIR / "2025" / "12"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_image = legacy_dir / "owner-legacy.png"
    legacy_image.write_bytes(PNG_BYTES)
    legacy_relative = legacy_image.relative_to(BACKEND_ROOT).as_posix()

    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            image_path=legacy_relative,
            image_hash="legacy-read-hash",
            status="pending",
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        expense_id = expense.id

    response = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")
    # File must STILL be at the legacy path; reading must not move it.
    assert legacy_image.is_file()


def test_protected_thumbnail_route_generates_for_legacy_path_without_migration(
    client: TestClient, *, identity,
) -> None:
    legacy_dir = TEST_UPLOAD_DIR / "2025" / "12"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_image = legacy_dir / "owner-legacy-thumb.png"
    legacy_image.write_bytes(PNG_BYTES)
    legacy_relative = legacy_image.relative_to(BACKEND_ROOT).as_posix()

    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            image_path=legacy_relative,
            thumbnail_path=None,
            image_hash="legacy-thumb-hash",
            status="pending",
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        expense_id = expense.id

    response = client.get(f"/api/expenses/{expense_id}/thumbnail", headers=identity.app_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert legacy_image.is_file()

    with SessionLocal() as db:
        refreshed = db.get(Expense, expense_id)
        assert refreshed is not None
        assert refreshed.thumbnail_path is not None
        assert "/2025/12/thumbs/" in refreshed.thumbnail_path.replace("\\", "/")
        assert (BACKEND_ROOT / refreshed.thumbnail_path).is_file()


def test_protected_image_route_rejects_legacy_path_for_non_default_ledger(
    client: TestClient, *, identity,
) -> None:
    """Unscoped legacy upload paths belong only to the default legacy ledger."""

    legacy_dir = TEST_UPLOAD_DIR / "2025" / "12"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_image = legacy_dir / "tester-legacy.png"
    legacy_image.write_bytes(PNG_BYTES)
    legacy_relative = legacy_image.relative_to(BACKEND_ROOT).as_posix()

    with SessionLocal() as db:
        expense = Expense(
            tenant_id="tester_1",
            image_path=legacy_relative,
            image_hash="tester-legacy-read-hash",
            status="pending",
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        expense_id = expense.id

    response = client.get(f"/api/expenses/{expense_id}/image", headers=identity.gray_app_headers)
    assert response.status_code == 404
    assert response.json()["error"] == "image_not_found"
    assert legacy_image.is_file()


def test_protected_image_route_rejects_absolute_and_drive_paths(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        original_path = expense.image_path

        for hostile in (
            "/etc/passwd",
            "\\\\server\\share\\evil.png",
            "C:\\Windows\\System32\\config.png",
            "uploads/../../etc/passwd",
            "uploads/owner/../../../etc/passwd",
        ):
            expense.image_path = hostile
            db.commit()
            response = client.get(
                f"/api/expenses/{expense_id}/image", headers=identity.app_headers
            )
            assert response.status_code == 404, hostile
            assert response.json()["error"] == "image_not_found"

        # Restore so the fixture teardown stays clean.
        expense.image_path = original_path
        db.commit()


def test_protected_image_route_rejects_paths_outside_uploads_root(
    client: TestClient, *, identity,
) -> None:
    """Even a relative path that resolves outside ``uploads/`` (e.g. via a
    symlink-equivalent traversal) must fail with image_not_found.
    """

    expense_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        # ``backups/foo.png`` is inside BACKEND_ROOT but NOT inside uploads/.
        expense.image_path = "backups/should-not-be-served.png"
        db.commit()

    response = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert response.status_code == 404
    assert response.json()["error"] == "image_not_found"
