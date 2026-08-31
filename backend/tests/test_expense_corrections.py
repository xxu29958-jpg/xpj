"""Confirmed Expense facts are corrected explicitly and retain immutable history."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from tests.api_contract_helpers import confirm_expense_api, patch_expense, upload_png
from tests.expense_correction_support import idem as _idem
from tests.expense_correction_support import manual_confirmed as _manual_confirmed
from tests.expense_correction_support import revision_history as _history
from tests.pairing_test_support import invitation_accept_payload


def test_manual_and_review_confirmation_each_create_one_baseline_revision(client: TestClient, *, identity) -> None:
    manual = _manual_confirmed(client, identity)
    assert manual["fact_revision"] == 1
    manual_history = _history(client, identity, manual["id"])
    assert manual_history["total"] == 1
    assert manual_history["items"][0]["change_kind"] == "confirmed"
    assert manual_history["items"][0]["before"] is None
    assert manual_history["items"][0]["after"]["merchant"] == "初始商家"

    pending_id = upload_png(client, identity=identity)
    patched = patch_expense(
        client,
        pending_id,
        headers=identity.app_headers,
        fields={"amount_cents": 3600, "merchant": "确认商家", "category": "购物"},
    )
    assert patched.status_code == 200, patched.text
    confirmed = confirm_expense_api(client, pending_id, headers=identity.app_headers)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["fact_revision"] == 1
    upload_history = _history(client, identity, pending_id)
    assert upload_history["total"] == 1
    assert upload_history["items"][0]["change_kind"] == "confirmed"
    assert upload_history["items"][0]["after"]["amount_cents"] == 3600


def test_correction_updates_current_projection_and_appends_before_after_fact(client: TestClient, *, identity) -> None:
    expense = _manual_confirmed(client, identity, amount_cents=1280)
    response = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "小票金额和商家录错了",
            "amount_cents": 1380,
            "merchant": "更正商家",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["expense"]["amount_cents"] == 1380
    assert body["expense"]["merchant"] == "更正商家"
    assert body["expense"]["fact_revision"] == 2
    assert body["revision"]["change_kind"] == "correction"
    assert body["revision"]["reason"] == "小票金额和商家录错了"
    assert body["revision"]["changed_fields"] == [
        "amount_cents",
        "original_amount_minor",
        "merchant",
    ]
    assert body["revision"]["before"]["amount_cents"] == 1280
    assert body["revision"]["after"]["amount_cents"] == 1380

    history = _history(client, identity, expense["id"])
    assert [item["change_kind"] for item in history["items"]] == [
        "correction",
        "confirmed",
    ]

    monthly = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert monthly.status_code == 200, monthly.text
    assert monthly.json()["total_amount_cents"] == 1380


def test_correction_can_explicitly_clear_optional_text_and_tags(client: TestClient, *, identity) -> None:
    expense = _manual_confirmed(
        client,
        identity,
        merchant="应被清空",
        tags="报销, 午餐",
    )

    response = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "移除错误附加信息",
            "merchant": "",
            "note": "",
            "tags": "",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["expense"]["merchant"] is None
    assert body["expense"]["note"] == ""
    assert body["expense"]["tags"] is None
    assert body["revision"]["changed_fields"] == ["merchant", "note", "tags"]
    assert body["revision"]["before"]["tags"] == "报销, 午餐"
    assert body["revision"]["after"]["tags"] is None


def test_correction_can_explicitly_clear_time_and_scores(client: TestClient, *, identity) -> None:
    created = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1280,
            "merchant": "带评分的账单",
            "category": "餐饮",
            "expense_time": "2026-05-04T00:30:00Z",
            "value_score": 5,
            "regret_score": 2,
        },
    )
    assert created.status_code == 200, created.text
    expense = created.json()

    response = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "移除不再成立的时间和评分",
            "expense_time": None,
            "value_score": None,
            "regret_score": None,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["expense"]["expense_time"] is None
    assert body["expense"]["value_score"] is None
    assert body["expense"]["regret_score"] is None
    assert set(body["revision"]["changed_fields"]) == {
        "expense_time",
        "value_score",
        "regret_score",
    }
    assert body["revision"]["before"]["value_score"] == 5
    assert body["revision"]["after"]["value_score"] is None


def test_correction_idempotent_replay_writes_exactly_one_revision(client: TestClient, *, identity) -> None:
    expense = _manual_confirmed(client, identity)
    key = str(uuid4())
    headers = _idem(identity.app_headers, key=key)
    payload = {
        "expected_row_version": expense["row_version"],
        "reason": "商家名称修正",
        "merchant": "唯一更正",
    }

    first = client.post(f"/api/expenses/{expense['id']}/corrections", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    replay = client.post(f"/api/expenses/{expense['id']}/corrections", headers=headers, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["expense"]["row_version"] == first.json()["expense"]["row_version"]
    assert replay.json()["revision"]["public_id"] == first.json()["revision"]["public_id"]

    later = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": first.json()["expense"]["row_version"],
            "reason": "后来又修正一次",
            "merchant": "后续权威值",
        },
    )
    assert later.status_code == 201, later.text

    # A late replay reports the original operation revision together with the
    # current canonical projection. Returning the first response's stale
    # Expense here would let Android overwrite the later fact in Room.
    replay_after_later = client.post(f"/api/expenses/{expense['id']}/corrections", headers=headers, json=payload)
    assert replay_after_later.status_code == 201, replay_after_later.text
    assert replay_after_later.json()["revision"]["public_id"] == first.json()["revision"]["public_id"]
    assert replay_after_later.json()["expense"]["merchant"] == "后续权威值"
    assert replay_after_later.json()["expense"]["fact_revision"] == later.json()["expense"]["fact_revision"]

    invitation = client.post(
        "/api/ledgers/owner/invitations",
        headers=identity.app_headers,
        json={"role": "member"},
    )
    assert invitation.status_code == 201, invitation.text
    accepted = client.post(
        "/api/invitations/accept",
        json=invitation_accept_payload(
            invitation.json()["invite_token"],
            account_name="correction-replay-member",
            device_name="correction-replay-phone",
        ),
    )
    assert accepted.status_code == 200, accepted.text
    cross_actor_replay = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers={
            "Authorization": f"Bearer {accepted.json()['session_token']}",
            "Idempotency-Key": key,
        },
        json=payload,
    )
    assert cross_actor_replay.status_code == 422, cross_actor_replay.text
    assert cross_actor_replay.json()["error"] == "idempotency_key_reused"

    history = _history(client, identity, expense["id"])
    assert history["total"] == 3
    assert sum(item["change_kind"] == "correction" for item in history["items"]) == 2


def test_stale_correction_is_409_and_leaves_no_revision(client: TestClient, *, identity) -> None:
    expense = _manual_confirmed(client, identity)
    first = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "先到的更正",
            "merchant": "先到",
        },
    )
    assert first.status_code == 201, first.text

    stale = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "过期更正",
            "merchant": "不应落库",
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"
    history = _history(client, identity, expense["id"])
    assert history["total"] == 2
    assert history["items"][0]["after"]["merchant"] == "先到"


def test_correction_requires_reason_real_change_and_idempotency_key(client: TestClient, *, identity) -> None:
    expense = _manual_confirmed(client, identity)
    url = f"/api/expenses/{expense['id']}/corrections"

    missing_key = client.post(
        url,
        headers=identity.app_headers,
        json={
            "expected_row_version": expense["row_version"],
            "reason": "需要幂等键",
            "merchant": "不会写入",
        },
    )
    assert missing_key.status_code == 422, missing_key.text
    assert missing_key.json()["error"] == "idempotency_key_required"

    blank_reason = client.post(
        url,
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "   ",
            "merchant": "不会写入",
        },
    )
    assert blank_reason.status_code == 422, blank_reason.text

    no_change = client.post(
        url,
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "没有实际变化",
            "merchant": expense["merchant"],
        },
    )
    assert no_change.status_code == 422, no_change.text
    assert no_change.json()["error"] == "expense_correction_no_changes"
    assert _history(client, identity, expense["id"])["total"] == 1


def test_confirmed_patch_is_retired_but_pending_patch_still_works(client: TestClient, *, identity) -> None:
    confirmed = _manual_confirmed(client, identity)
    blocked = client.patch(
        f"/api/expenses/{confirmed['id']}",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": confirmed["row_version"],
            "merchant": "旧后门",
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"] == "expense_correction_required"

    pending_id = upload_png(client, identity=identity)
    pending = patch_expense(
        client,
        pending_id,
        headers=identity.app_headers,
        fields={"merchant": "Pending 仍可编辑"},
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["merchant"] == "Pending 仍可编辑"

    confirmed_reject = client.post(
        f"/api/expenses/{confirmed['id']}/reject",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": confirmed["row_version"]},
    )
    assert confirmed_reject.status_code == 409, confirmed_reject.text
    assert confirmed_reject.json()["error"] == "expense_reversal_required"


def test_revision_read_is_tenant_scoped_and_correction_is_writer_only(client: TestClient, *, identity) -> None:
    expense = _manual_confirmed(client, identity)
    url = f"/api/expenses/{expense['id']}/corrections"
    payload = {
        "expected_row_version": expense["row_version"],
        "reason": "权限测试",
        "merchant": "不应写入",
    }

    no_auth = client.post(
        url,
        headers={"Idempotency-Key": str(uuid4())},
        json=payload,
    )
    assert no_auth.status_code == 401, no_auth.text

    foreign_history = client.get(
        f"/api/expenses/{expense['id']}/revisions",
        headers=identity.gray_app_headers,
    )
    assert foreign_history.status_code == 404, foreign_history.text

    with SessionLocal() as db:
        membership = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert membership is not None
        membership.role = "viewer"
        db.commit()
    viewer = client.post(url, headers=_idem(identity.app_headers), json=payload)
    assert viewer.status_code == 403, viewer.text
    assert viewer.json()["error"] == "permission_denied"


def test_revision_history_is_newest_first_and_paginated(client: TestClient, *, identity) -> None:
    expense = _manual_confirmed(client, identity)
    current = expense
    for merchant in ("第二版", "第三版"):
        response = client.post(
            f"/api/expenses/{expense['id']}/corrections",
            headers=_idem(identity.app_headers),
            json={
                "expected_row_version": current["row_version"],
                "reason": f"改为{merchant}",
                "merchant": merchant,
            },
        )
        assert response.status_code == 201, response.text
        current = response.json()["expense"]

    first_page = _history(client, identity, expense["id"], page=1, page_size=2)
    assert first_page["total"] == 3
    assert first_page["page"] == 1
    assert [item["revision_number"] for item in first_page["items"]] == [3, 2]
    second_page = _history(client, identity, expense["id"], page=2, page_size=2)
    assert [item["revision_number"] for item in second_page["items"]] == [1]


def test_revision_history_snapshot_keeps_earliest_revision_reachable_after_new_corrections(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = _manual_confirmed(client, identity)
    current = expense
    for merchant in ("第二版", "第三版"):
        response = client.post(
            f"/api/expenses/{expense['id']}/corrections",
            headers=_idem(identity.app_headers),
            json={
                "expected_row_version": current["row_version"],
                "reason": f"改为{merchant}",
                "merchant": merchant,
            },
        )
        assert response.status_code == 201, response.text
        current = response.json()["expense"]

    first_page = _history(client, identity, expense["id"], page=1, page_size=2)
    assert first_page["snapshot_revision"] == 3
    assert [item["revision_number"] for item in first_page["items"]] == [3, 2]

    for merchant in ("第四版", "第五版"):
        response = client.post(
            f"/api/expenses/{expense['id']}/corrections",
            headers=_idem(identity.app_headers),
            json={
                "expected_row_version": current["row_version"],
                "reason": f"改为{merchant}",
                "merchant": merchant,
            },
        )
        assert response.status_code == 201, response.text
        current = response.json()["expense"]

    anchored_second_page = _history(
        client,
        identity,
        expense["id"],
        page=2,
        page_size=2,
        snapshot_revision=first_page["snapshot_revision"],
    )
    assert anchored_second_page["snapshot_revision"] == 3
    assert anchored_second_page["total"] == 3
    assert [item["revision_number"] for item in anchored_second_page["items"]] == [1]

    refreshed_first_page = _history(client, identity, expense["id"], page=1, page_size=2)
    assert refreshed_first_page["snapshot_revision"] == 5
    assert refreshed_first_page["total"] == 5
    assert [item["revision_number"] for item in refreshed_first_page["items"]] == [5, 4]


def test_one_correction_can_replace_items_and_splits_without_legacy_backdoors(client: TestClient, *, identity) -> None:
    expense = _manual_confirmed(client, identity)
    with SessionLocal() as db:
        membership = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert membership is not None
        member_id = int(membership.id)

    corrected = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "补齐原小票明细和家庭分摊",
            "items": [
                {
                    "name": "早餐套餐",
                    "kind": "product",
                    "amount_cents": 1280,
                    "category": "餐饮",
                }
            ],
            "splits": [{"member_id": member_id, "amount_cents": 1280, "note": "本人"}],
        },
    )
    assert corrected.status_code == 201, corrected.text
    revision = corrected.json()["revision"]
    assert "items" in revision["changed_fields"]
    assert "splits" in revision["changed_fields"]
    assert revision["after"]["items"][0]["name"] == "早餐套餐"
    assert revision["after"]["splits"][0]["member_id"] == member_id

    current = corrected.json()["expense"]
    old_items = client.put(
        f"/api/expenses/{expense['id']}/items",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": current["row_version"], "items": []},
    )
    assert old_items.status_code == 409, old_items.text
    assert old_items.json()["error"] == "expense_correction_required"
    old_splits = client.put(
        f"/api/expenses/{expense['id']}/splits",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": current["row_version"], "splits": []},
    )
    assert old_splits.status_code == 409, old_splits.text
    assert old_splits.json()["error"] == "expense_correction_required"


def test_amount_correction_allows_partial_but_rejects_overallocated_splits_atomically(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = _manual_confirmed(client, identity, amount_cents=1280)
    with SessionLocal() as db:
        membership = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert membership is not None
        member_id = int(membership.id)

    balanced = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "记录家庭分摊",
            "splits": [{"member_id": member_id, "amount_cents": 1280}],
        },
    )
    assert balanced.status_code == 201, balanced.text
    balanced_expense = balanced.json()["expense"]
    history_before = _history(client, identity, expense["id"])

    overallocated = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": balanced_expense["row_version"],
            "reason": "金额应更低",
            "amount_cents": 1200,
        },
    )
    assert overallocated.status_code == 422, overallocated.text
    assert overallocated.json()["error"] == "expense_split_total_exceeds_parent"
    unchanged = client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers).json()
    assert unchanged["amount_cents"] == 1280
    assert unchanged["row_version"] == balanced_expense["row_version"]
    assert unchanged["fact_revision"] == balanced_expense["fact_revision"]
    assert _history(client, identity, expense["id"])["total"] == history_before["total"]

    partial = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": unchanged["row_version"],
            "reason": "金额应更高，保留现有分摊",
            "amount_cents": 1380,
        },
    )
    assert partial.status_code == 201, partial.text
    listed = client.get(f"/api/expenses/{expense['id']}/splits", headers=identity.app_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["splits_total_amount_cents"] == 1280
    assert listed.json()["mismatch_cents"] == 100
