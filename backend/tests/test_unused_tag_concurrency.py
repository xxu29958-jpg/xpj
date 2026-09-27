"""Unused-tag cleanup and a real in-flight financial tag writer share one identity."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import suppress
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.services import tag_management_service
from tests._infra.client import make_test_client
from tests._infra.tag_helpers import expense_row, manual_expense, tag_index, tag_links


def _record_with_original_tag(headers: dict[str, str]) -> dict:
    with make_test_client() as client:
        return manual_expense(client, headers, tags="工作", merchant="清理进行中新记账")


def test_unused_cleanup_cannot_rewrite_a_new_expense_or_hide_its_reused_tag(client: TestClient, identity, monkeypatch) -> None:
    original = manual_expense(client, identity.app_headers, tags="工作", merchant="原使用者")
    correction = client.post(
        f"/api/expenses/{original['id']}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": original["row_version"], "reason": "移除误加标签", "tags": ""},
    )
    assert correction.status_code == 201, correction.text
    unused = tag_index(client, identity.app_headers)["工作"]
    assert unused["usage_count"] == 0
    claim = tag_management_service._claim_tag_soft_delete
    recording = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        def claim_then_record(*args, **kwargs):
            nonlocal recording
            changed = claim(*args, **kwargs)
            assert changed == 1
            recording = pool.submit(_record_with_original_tag, identity.app_headers)
            # A correctly serialized writer may continue only after cleanup commits.
            with suppress(TimeoutError):
                recording.result(timeout=2)
            return changed

        with monkeypatch.context() as patch:
            patch.setattr(tag_management_service, "_claim_tag_soft_delete", claim_then_record)
            with SessionLocal() as db:
                cleanup = tag_management_service.delete_tag(
                    db, tenant_id="owner", public_id=unused["public_id"],
                    expected_row_version=unused["row_version"], require_orphan=True,
                )
        assert recording is not None
        accepted = recording.result(timeout=10)

    assert cleanup.affected_expense_count == 0, "Unused cleanup cannot remove a financial tag accepted concurrently"
    assert expense_row("清理进行中新记账") == (accepted["id"], accepted["row_version"], "工作")
    assert tag_links(accepted["id"]) == ["工作"]
    current = tag_index(client, identity.app_headers)["工作"]
    assert current["public_id"] == unused["public_id"] and current["usage_count"] == 1
