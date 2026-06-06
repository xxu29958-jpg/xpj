"""Owner Console 标签清理 panel (ADR-0043 slice C).

Lists orphan tags (usage_count == 0) for the default ledger and soft-deletes
them via the shared tag_management_service. Loopback-gated like every /owner
page.
"""

from __future__ import annotations

import re as _re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local
from tests._infra.tag_helpers import manual_expense, tag_index


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    """Bypass Owner Console loopback gate for the test."""
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def _seed_orphan_tag(client: TestClient, headers: dict[str, str]) -> None:
    """Create an expense tagged 出差+工作, then drop 工作 → 工作 becomes orphan."""
    from api_contract_helpers import patch_expense

    from tests._infra.tag_helpers import expense_row

    manual_expense(client, headers, tags="出差, 工作", merchant="A")
    a_id, _, _ = expense_row("A")
    patched = patch_expense(client, a_id, headers=headers, fields={"tags": "出差"})
    assert patched.status_code == 200, patched.text


def test_owner_tag_cleanup_get_lists_orphans(local_client: TestClient, *, identity) -> None:
    _seed_orphan_tag(local_client, identity.app_headers)
    resp = local_client.get("/owner/tag-cleanup")
    assert resp.status_code == 200
    assert "标签清理" in resp.text
    assert "工作" in resp.text  # the orphan
    # The in-use tag is NOT listed (only orphans).
    assert resp.text.count("/owner/tag-cleanup/delete") == 1


def test_owner_tag_cleanup_delete_removes_orphan(local_client: TestClient, *, identity) -> None:
    _seed_orphan_tag(local_client, identity.app_headers)
    page = local_client.get("/owner/tag-cleanup")
    m = _re.search(
        r"name=\"public_id\" value=\"([^\"]+)\".*?name=\"expected_row_version\" value=\"([^\"]+)\"",
        page.text,
        flags=_re.DOTALL,
    )
    assert m, page.text[:1500]
    public_id, token = m.group(1), m.group(2)

    deleted = local_client.post(
        "/owner/tag-cleanup/delete",
        data={"public_id": public_id, "expected_row_version": token},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    # Orphan is gone from both the panel and the live tag index.
    assert "工作" not in tag_index(local_client, identity.app_headers)
    page = local_client.get("/owner/tag-cleanup")
    assert "当前没有孤儿标签" in page.text


def test_owner_tag_cleanup_remote_returns_403(client: TestClient, *, identity) -> None:
    # Both the GET panel AND the POST mutate must be loopback-gated. There is no
    # owner route-inventory guard (unlike /web), so this test is the only thing
    # that catches a dropped LocalOnly on the delete handler.
    assert client.get("/owner/tag-cleanup").status_code == 403
    assert (
        client.post(
            "/owner/tag-cleanup/delete",
            data={"public_id": "x", "expected_row_version": 1},
        ).status_code
        == 403
    )
