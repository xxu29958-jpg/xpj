"""Unused-tag cleanup and a real in-flight financial tag writer share one identity."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import suppress
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import AppError
from app.services import tag_management_service, tag_service
from tests._infra.client import make_test_client
from tests._infra.tag_helpers import expense_row, manual_expense, tag_index, tag_links


def _record_with_original_tag(headers: dict[str, str]) -> dict:
    with make_test_client() as client:
        return manual_expense(client, headers, tags="工作", merchant="清理进行中新记账")


def _unused_tag(client: TestClient, headers: dict[str, str]) -> dict:
    original = manual_expense(client, headers, tags="工作", merchant="原使用者")
    correction = client.post(
        f"/api/expenses/{original['id']}/corrections",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": original["row_version"], "reason": "移除误加标签", "tags": ""},
    )
    assert correction.status_code == 201, correction.text
    unused = tag_index(client, headers)["工作"]
    assert unused["usage_count"] == 0
    return unused


@pytest.mark.real_db
def test_unused_cleanup_cannot_rewrite_a_new_expense_or_hide_its_reused_tag(client: TestClient, identity, monkeypatch) -> None:
    unused = _unused_tag(client, identity.app_headers)
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


@pytest.mark.real_db
def test_unused_cleanup_waits_for_an_existing_tag_writer_and_rejects_its_now_used_tag(
    client: TestClient, identity, monkeypatch,
) -> None:
    unused = _unused_tag(client, identity.app_headers)
    writer_ready, release_writer, cleanup_started = Event(), Event(), Event()
    ensure_tag = tag_service._ensure_tag
    claim = tag_management_service._claim_tag_soft_delete

    def pause_original_writer(*args, **kwargs):
        tag = ensure_tag(*args, **kwargs)
        writer_ready.set()
        assert release_writer.wait(timeout=10), "The original financial writer was not released"
        return tag

    def mark_cleanup_started(*args, **kwargs):
        cleanup_started.set()
        return claim(*args, **kwargs)

    def cleanup():
        with SessionLocal() as db:
            try:
                return tag_management_service.delete_tag(
                    db, tenant_id="owner", public_id=unused["public_id"],
                    expected_row_version=unused["row_version"], require_orphan=True,
                )
            except AppError as error:
                return error.error

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(tag_service, "_ensure_tag", pause_original_writer)
        patch.setattr(tag_management_service, "_claim_tag_soft_delete", mark_cleanup_started)
        recording = pool.submit(_record_with_original_tag, identity.app_headers)
        try:
            assert writer_ready.wait(timeout=5)
            cleaning = pool.submit(cleanup)
            assert cleanup_started.wait(timeout=5)
            with suppress(TimeoutError):
                cleaning.result(timeout=1)
        finally:
            release_writer.set()
        accepted = recording.result(timeout=10)
        assert cleaning.result(timeout=10) == "state_conflict"

    assert expense_row("清理进行中新记账") == (accepted["id"], accepted["row_version"], "工作")
    assert tag_links(accepted["id"]) == ["工作"]
    current = tag_index(client, identity.app_headers)["工作"]
    assert current["public_id"] == unused["public_id"] and current["usage_count"] == 1
