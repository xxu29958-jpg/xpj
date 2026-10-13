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


def test_full_history_reaches_before_twenty_offsets_and_keeps_its_original_prefix(client: TestClient, *, identity) -> None:
    expense = _manual_confirmed(client, identity, amount_cents=12000)
    current = _correct_merchant(client, identity, expense, "街角小馆")
    for index in range(21):
        created = client.post(f"/api/expenses/{expense['id']}/offsets", headers=_idem(identity.app_headers),
            json={"kind": "refund", "original_amount_minor": 1, "accounting_date": "2026-10-05",
                "reason": f"分次退回{index}", "expected_row_version": current["row_version"]})
        assert created.status_code == 201, created.text
        bundle = created.json()
        current = bundle["root"]
    first = _history(client, identity, expense["id"], include_offsets=True, page_size=10)
    assert first["total"] == 23
    assert len(first["items"]) == 10
    assert all(item["change_kind"] == "created" for item in first["items"])
    assert all(item["after"]["original_currency_code"] == "CNY" for item in first["items"])
    offset = bundle["active_offsets"][0]
    voided = client.post(f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/voids",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": offset["row_version"], "void_reason": "撤销一次退回"})
    assert voided.status_code == 201, voided.text
    _correct_merchant(client, identity, voided.json()["root"], "更新后的商家")
    rows = list(first["items"])
    for page in (2, 3):
        older = _history(client, identity, expense["id"], include_offsets=True, page=page, page_size=10,
            snapshot_revision=first["snapshot_revision"], offset_snapshot_id=first["offset_snapshot_id"])
        assert older["total"] == first["total"]
        assert older["offset_snapshot_id"] == first["offset_snapshot_id"]
        rows.extend(older["items"])
    assert len({row["public_id"] for row in rows}) == 23
    assert rows[-1]["change_kind"] == "confirmed"
    assert rows[-1]["after"]["amount_cents"] == 12000
    assert sum(row["change_kind"] == "created" for row in rows) == 21
    fresh = _history(client, identity, expense["id"], include_offsets=True, page_size=50)
    assert fresh["total"] == 25
    assert fresh["items"][1]["change_kind"] == "void"
    assert fresh["items"][1]["before"]["status"] == "active"
    assert fresh["items"][1]["after"]["status"] == "voided"
    # Existing correction-only callers retain their original contract.
    assert _history(client, identity, expense["id"])["total"] == 3


def test_full_history_keeps_parent_ledger_authorization(client: TestClient, *, identity) -> None:
    from tests.test_bill_split import _seed_receiver
    from tests.test_bill_split_security_regressions import _bearer_for_account_ledger

    expense = _manual_confirmed(client, identity)
    account = _seed_receiver(ledger_id="history-other")
    url = f"/api/expenses/{expense['id']}/revisions?include_offsets=true"
    assert client.get(url).status_code == 401
    other = _bearer_for_account_ledger(account, "history-other")
    response = client.get(url, headers=other)
    assert response.status_code == 404, response.text
