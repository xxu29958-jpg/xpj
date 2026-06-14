"""Tenant-scoped idempotency for member proposal confirmations."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.debt_proposal_helpers import (
    _create_member_debt,
    _member_headers,
    _mint_member_actor,
    _propose,
)


def test_confirm_repayment_key_can_be_reused_in_another_ledger(
    client: TestClient, *, identity
) -> None:
    owner_member_id, owner_member_token = _mint_member_actor(ledger_id="owner")
    tester_member_id, tester_member_token = _mint_member_actor(ledger_id="tester_1")
    owner_debt = _create_member_debt(
        client,
        identity.app_headers,
        direction="owed_to_me",
        member_account_id=owner_member_id,
        ledger_id="owner",
    )
    tester_debt = _create_member_debt(
        client,
        identity.gray_app_headers,
        direction="owed_to_me",
        member_account_id=tester_member_id,
        ledger_id="tester_1",
    )
    owner_proposal = _propose(
        client,
        _member_headers(owner_member_token),
        owner_debt["public_id"],
        proposed_amount_cents=20000,
    ).json()
    tester_proposal = _propose(
        client,
        _member_headers(tester_member_token),
        tester_debt["public_id"],
        proposed_amount_cents=20000,
    ).json()
    key = str(uuid4())

    owner_confirm = client.post(
        (
            f"/api/debts/{owner_debt['public_id']}/repayment-proposals/"
            f"{owner_proposal['public_id']}/confirm"
        ),
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"expected_row_version": owner_debt["row_version"]},
    )
    assert owner_confirm.status_code == 201, owner_confirm.json()

    tester_confirm = client.post(
        (
            f"/api/debts/{tester_debt['public_id']}/repayment-proposals/"
            f"{tester_proposal['public_id']}/confirm"
        ),
        headers={**identity.gray_app_headers, "Idempotency-Key": key},
        json={"expected_row_version": tester_debt["row_version"]},
    )
    assert tester_confirm.status_code == 201, tester_confirm.json()
    assert owner_confirm.json()["remaining_amount_cents"] == 30000
    assert tester_confirm.json()["remaining_amount_cents"] == 30000
