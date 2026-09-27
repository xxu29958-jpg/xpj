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
from app.services import tag_management_service, tag_mutation_expense_projection_service, tag_service
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
def test_retaining_a_tag_during_correction_preserves_the_fact_and_rejects_a_concurrent_stale_rename(
    client: TestClient, identity, monkeypatch,
) -> None:
    original = manual_expense(client, identity.app_headers, tags="工作", merchant="原始账单")
    tag = tag_index(client, identity.app_headers)["工作"]
    correction_ready, rename_projection_ready = Event(), Event()
    ensure_tag = tag_service._ensure_tag
    claim_projection = tag_mutation_expense_projection_service.claim_row_with_token
    correction_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    correction_url = f"/api/expenses/{original['id']}/corrections"
    payload = {
        "expected_row_version": original["row_version"], "reason": "更正商家，保留原标签",
        "merchant": "更正后的商家", "tags": "工作",
    }

    def retain_tag_after_rename_claim(*args, **kwargs):
        correction_ready.set()
        assert rename_projection_ready.wait(timeout=10), "Rename never reached the original Expense projection"
        return ensure_tag(*args, **kwargs)

    def mark_original_projection_claim(*args, **kwargs):
        # Rename already holds the Tag row and captured the original Expense OCC.
        rename_projection_ready.set()
        return claim_projection(*args, **kwargs)

    def correct_original():
        with make_test_client() as writer:
            return writer.post(correction_url, headers=correction_headers, json=payload)

    def rename_original():
        with make_test_client() as writer:
            return writer.post(
                f"/api/tags/{tag['public_id']}/rename", headers=identity.app_headers,
                json={"expected_row_version": tag["row_version"], "name": "办公"},
            )

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(tag_service, "_ensure_tag", retain_tag_after_rename_claim)
        patch.setattr(tag_mutation_expense_projection_service, "claim_row_with_token", mark_original_projection_claim)
        correcting = pool.submit(correct_original)
        assert correction_ready.wait(timeout=10)
        renaming = pool.submit(rename_original)
        accepted, conflict = correcting.result(timeout=15), renaming.result(timeout=15)

    assert accepted.status_code == 201, accepted.text
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"] == "state_conflict"
    fact = accepted.json()["expense"]
    assert expense_row("更正后的商家") == (original["id"], fact["row_version"], "工作")
    assert fact["amount_cents"] == original["amount_cents"] == 1000
    assert fact["home_currency"] == original["home_currency"] == "CNY"
    assert tag_links(original["id"]) == ["工作"]
    tags = tag_index(client, identity.app_headers)
    assert set(tags) == {"工作"}
    assert tags["工作"]["public_id"] == tag["public_id"]
    assert tags["工作"]["row_version"] == tag["row_version"]
    replay = client.post(correction_url, headers=correction_headers, json=payload)
    assert replay.status_code == 201 and replay.json() == accepted.json()
    history = client.get(f"/api/expenses/{original['id']}/revisions", headers=identity.app_headers)
    assert history.status_code == 200 and history.json()["total"] == 2


@pytest.mark.real_db
@pytest.mark.parametrize("operation", ["delete", "rename", "merge"])
def test_unused_cleanup_waits_for_an_existing_tag_writer_and_rejects_its_now_used_tag(
    client: TestClient, identity, monkeypatch, operation: str,
) -> None:
    target = None
    if operation == "merge":
        manual_expense(client, identity.app_headers, tags="出差", merchant="原合并目标")
        target = tag_index(client, identity.app_headers)["出差"]
    unused = _unused_tag(client, identity.app_headers)
    writer_ready, release_writer, cleanup_started = Event(), Event(), Event()
    ensure_tag = tag_service._ensure_tag
    claim = tag_management_service._unused_tag_claim_conditions

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
                if operation == "merge":
                    assert target is not None
                    return tag_management_service.merge_tags(
                        db, tenant_id="owner", source_public_id=unused["public_id"],
                        source_row_version=unused["row_version"], target_public_id=target["public_id"],
                        target_row_version=target["row_version"], require_orphan=True,
                    )
                if operation == "rename":
                    return tag_management_service.rename_tag(
                        db, tenant_id="owner", public_id=unused["public_id"],
                        expected_row_version=unused["row_version"], name="办公", require_orphan=True,
                    )
                return tag_management_service.delete_tag(
                    db, tenant_id="owner", public_id=unused["public_id"],
                    expected_row_version=unused["row_version"], require_orphan=True,
                )
            except AppError as error:
                return error.error

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(tag_service, "_ensure_tag", pause_original_writer)
        patch.setattr(tag_management_service, "_unused_tag_claim_conditions", mark_cleanup_started)
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
    if target is not None:
        assert tag_index(client, identity.app_headers)["出差"] == target
