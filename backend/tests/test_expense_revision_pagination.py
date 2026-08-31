"""Confirmed-expense revision pages keep one immutable server snapshot."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.expense_correction_support import idem as _idem
from tests.expense_correction_support import manual_confirmed as _manual_confirmed
from tests.expense_correction_support import revision_history as _history


def _correct_merchant(client: TestClient, identity, expense: dict, merchant: str) -> dict:
    response = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=_idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": f"改为{merchant}",
            "merchant": merchant,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["expense"]


def test_revision_history_is_newest_first_and_paginated(client: TestClient, *, identity) -> None:
    expense = _manual_confirmed(client, identity)
    current = expense
    for merchant in ("第二版", "第三版"):
        current = _correct_merchant(client, identity, current, merchant)

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
        current = _correct_merchant(client, identity, current, merchant)

    first_page = _history(client, identity, expense["id"], page=1, page_size=2)
    assert first_page["snapshot_revision"] == 3
    assert [item["revision_number"] for item in first_page["items"]] == [3, 2]

    for merchant in ("第四版", "第五版"):
        current = _correct_merchant(client, identity, current, merchant)

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
