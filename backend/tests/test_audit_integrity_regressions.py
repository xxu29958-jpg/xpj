from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    AccountMovement,
    CreditFacility,
    Debt,
    ExchangeRate,
    Expense,
    FinancialAccount,
    Ledger,
)
from app.schemas.funds import FundingPart
from app.services.expense_funding_service import publish_expense_funding
from app.services.time_service import now_utc
from tests.bill_split_test_support import _seed_receiver, _split_headers
from tests.expense_correction_support import idem, manual_confirmed


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner_id = db.scalar(select(Ledger.owner_account_id).where(Ledger.ledger_id == "owner"))
        assert owner_id is not None
        return int(owner_id)


def _create_account(
    client: TestClient,
    identity,
    *,
    name: str,
    kind: str,
    currency: str = "CNY",
    opening_amount_minor: int = 50000,
) -> dict:
    resp = client.post(
        "/api/funds/accounts",
        headers=idem(identity.app_headers),
        json={
            "name": name,
            "kind": kind,
            "currency_code": currency,
            "opening_amount_minor": opening_amount_minor,
            "opening_date": "2026-05-01",
            "opening_source": "核对",
            "visibility": "ledger",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_reversal_blocks_amount_correction_and_preserves_funding_consistency(
    client: TestClient,
    identity,
) -> None:
    account = _create_account(client, identity, name="储蓄卡", kind="bank")
    expense = manual_confirmed(client, identity, amount_cents=10000)

    funded = client.post(
        f"/api/expenses/{expense['id']}/funding",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "确认付款账户",
            "parts": [
                {
                    "account_public_id": account["public_id"],
                    "account_row_version": account["row_version"],
                    "component_id": "primary",
                    "expense_amount_minor": 10000,
                    "account_amount_minor": 10000,
                    "expense_currency_code": "CNY",
                    "account_currency_code": "CNY",
                }
            ],
        },
    )
    assert funded.status_code == 200, funded.text
    funded_version = funded.json()["expense_row_version"]

    reversed_resp = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "reversal",
            "accounting_date": "2026-05-06",
            "reason": "全额冲正",
            "expected_row_version": funded_version,
        },
    )
    assert reversed_resp.status_code == 201, reversed_resp.text
    root_version = reversed_resp.json()["root"]["row_version"]

    blocked = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "amount_cents": 6000,
            "reason": "冲正期间尝试改金额",
            "expected_row_version": root_version,
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"] == "expense_reversal_active"

    metadata_only = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "note": "仅改备注允许",
            "reason": "补充说明",
            "expected_row_version": root_version,
        },
    )
    assert metadata_only.status_code == 201, metadata_only.text


def test_partial_refund_blocks_lowering_expense_below_refunded_total(
    client: TestClient,
    identity,
) -> None:
    expense = manual_confirmed(client, identity, amount_cents=10000)

    refund = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 8000,
            "accounting_date": "2026-05-05",
            "reason": "部分退款",
            "expected_row_version": expense["row_version"],
        },
    )
    assert refund.status_code == 201, refund.text
    version_after_refund = refund.json()["root"]["row_version"]

    too_low = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "amount_cents": 5000,
            "reason": "低于已退款金额",
            "expected_row_version": version_after_refund,
        },
    )
    assert too_low.status_code == 409, too_low.text
    assert too_low.json()["error"] == "expense_refund_exceeds_remaining"

    valid_lower = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "amount_cents": 8000,
            "reason": "等于已退款金额合法",
            "expected_row_version": version_after_refund,
        },
    )
    assert valid_lower.status_code == 201, valid_lower.text


def test_reversed_expense_cannot_create_new_bill_split_invitation(
    client: TestClient,
    identity,
) -> None:
    receiver_account_id = _seed_receiver()
    expense = manual_confirmed(client, identity, amount_cents=10000)

    reversed_resp = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "reversal",
            "accounting_date": "2026-05-06",
            "reason": "冲正",
            "expected_row_version": expense["row_version"],
        },
    )
    assert reversed_resp.status_code == 201, reversed_resp.text
    root_version = reversed_resp.json()["root"]["row_version"]

    invite = client.post(
        f"/api/expenses/{expense['id']}/split-invite",
        headers=_split_headers(client, identity.app_headers),
        json={
            "receiver_account_id": receiver_account_id,
            "amount_cents": 5000,
            "expected_row_version": root_version,
        },
    )
    assert invite.status_code == 409, invite.text
    assert invite.json()["error"] == "expense_reversal_active"


def test_multi_part_funding_cumulative_rounding_never_produces_positive_credit_draw(
    client: TestClient,
    identity,
) -> None:
    owner_account_id = _owner_account_id()
    credit = _create_account(
        client,
        identity,
        name="外币信用卡",
        kind="credit",
        currency="JPY",
        opening_amount_minor=0,
    )
    with SessionLocal() as db:
        account = db.scalar(
            select(FinancialAccount).where(FinancialAccount.public_id == credit["public_id"])
        )
        assert account is not None
        expense = Expense(
            tenant_id="owner",
            amount_cents=2,
            home_currency_code="CNY",
            original_currency_code="JPY",
            original_amount_minor=4,
            exchange_rate_to_cny=Decimal("0.00500000"),
            exchange_rate_date=date(2026, 5, 5),
            exchange_rate_source="manual",
            merchant="便利店",
            category="餐饮",
            status="confirmed",
            accounting_date=date(2026, 5, 5),
            calendar_revision=1,
            confirmed_at=now_utc(),
        )
        db.add(
            ExchangeRate(
                tenant_id="owner",
                home_currency_code="CNY",
                currency_code="JPY",
                rate_date=date(2026, 5, 6),
                rate_to_cny=Decimal("0.00500000"),
                source="manual",
            )
        )
        db.add(expense)
        db.flush()
        parts = [
            FundingPart(
                account_public_id=account.public_id,
                account_row_version=account.row_version,
                component_id=f"c{i}",
                expense_amount_minor=1,
                account_amount_minor=1,
                expense_currency_code="JPY",
                account_currency_code="JPY",
                included_in_opening=False,
            )
            for i in range(4)
        ]
        publish_expense_funding(
            db,
            expense=expense,
            parts=parts,
            actor_account_id=owner_account_id,
        )
        db.commit()

        movements = list(
            db.scalars(
                select(AccountMovement)
                .where(AccountMovement.account_id == account.id, AccountMovement.kind == "credit_draw")
                .order_by(AccountMovement.id)
            )
        )
        assert [m.amount_minor for m in movements] == [-1, -1, -1, -1]
        assert [m.home_amount_cents for m in movements] == [-1, 0, -1, 0]
        assert sum(m.home_amount_cents for m in movements) == -2
        draw_public_ids = [m.public_id for m in movements]

        facility = db.scalar(select(CreditFacility).where(CreditFacility.account_id == account.id))
        assert facility is not None
        debt = db.get(Debt, facility.debt_id)
        assert debt is not None
        debt_public_id = debt.public_id
        credit_row_version = account.row_version

    debt_view = client.get(f"/api/debts/{debt_public_id}", headers=identity.app_headers)
    assert debt_view.status_code == 200, debt_view.text
    assert debt_view.json()["remaining_amount_cents"] == 2

    payer = _create_account(
        client,
        identity,
        name="外币储蓄卡",
        kind="bank",
        currency="JPY",
        opening_amount_minor=100,
    )
    repay = client.post(
        f"/api/funds/accounts/{credit['public_id']}/repay",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": credit_row_version,
            "calendar_revision": 1,
            "payer_public_id": payer["public_id"],
            "payer_row_version": payer["row_version"],
            "principal_minor": 4,
            "payer_amount_minor": 4,
            "occurred_on": "2026-05-06",
            "note": "全额清偿验证",
            "draw_allocations": [
                {"draw_public_id": draw_id, "principal_minor": 1}
                for draw_id in draw_public_ids
            ],
        },
    )
    assert repay.status_code == 200, repay.text
    settled_view = client.get(f"/api/debts/{debt_public_id}", headers=identity.app_headers)
    assert settled_view.status_code == 200, settled_view.text
    assert settled_view.json()["remaining_amount_cents"] == 0


def test_mixed_opening_and_live_funding_can_void_reversal(
    client: TestClient,
    identity,
) -> None:
    opening_account = client.post(
        "/api/funds/accounts",
        headers=idem(identity.app_headers),
        json={
            "name": "老卡",
            "kind": "bank",
            "currency_code": "CNY",
            "opening_amount_minor": 50000,
            "opening_date": "2026-05-10",
            "opening_source": "核对",
            "visibility": "ledger",
        },
    )
    assert opening_account.status_code == 200, opening_account.text
    opening_acc = opening_account.json()
    live_acc = _create_account(client, identity, name="新卡", kind="bank")
    expense = manual_confirmed(client, identity, amount_cents=10000)

    funded = client.post(
        f"/api/expenses/{expense['id']}/funding",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "混合付款",
            "parts": [
                {
                    "account_public_id": opening_acc["public_id"],
                    "account_row_version": opening_acc["row_version"],
                    "component_id": "open_part",
                    "expense_amount_minor": 4000,
                    "account_amount_minor": 4000,
                    "expense_currency_code": "CNY",
                    "account_currency_code": "CNY",
                    "included_in_opening": True,
                },
                {
                    "account_public_id": live_acc["public_id"],
                    "account_row_version": live_acc["row_version"],
                    "component_id": "live_part",
                    "expense_amount_minor": 6000,
                    "account_amount_minor": 6000,
                    "expense_currency_code": "CNY",
                    "account_currency_code": "CNY",
                    "included_in_opening": False,
                },
            ],
        },
    )
    assert funded.status_code == 200, funded.text
    funded_version = funded.json()["expense_row_version"]

    rev = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "reversal",
            "accounting_date": "2026-05-12",
            "reason": "混合付款冲正",
            "expected_row_version": funded_version,
        },
    )
    assert rev.status_code == 201, rev.text
    offset = rev.json()["active_offsets"][0]

    voided = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/voids",
        headers=idem(identity.app_headers),
        json={
            "void_reason": "误冲正撤销",
            "expected_row_version": offset["row_version"],
        },
    )
    assert voided.status_code == 201, voided.text
    funding_after = client.get(f"/api/expenses/{expense['id']}/funding", headers=identity.app_headers)
    assert funding_after.status_code == 200, funding_after.text
    assert sum(part["expense_amount_minor"] for part in funding_after.json()["parts"]) == 10000


def test_legacy_reversed_expense_amount_drift_can_be_repaired_and_voided(
    client: TestClient,
    identity,
) -> None:
    opening_account = client.post(
        "/api/funds/accounts",
        headers=idem(identity.app_headers),
        json={
            "name": "历史期初卡",
            "kind": "bank",
            "currency_code": "CNY",
            "opening_amount_minor": 50000,
            "opening_date": "2026-05-10",
            "opening_source": "核对",
            "visibility": "ledger",
        },
    )
    assert opening_account.status_code == 200, opening_account.text
    opening_acc = opening_account.json()
    live_acc = _create_account(client, identity, name="老数据卡", kind="bank")
    expense = manual_confirmed(client, identity, amount_cents=10000)

    funded = client.post(
        f"/api/expenses/{expense['id']}/funding",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "混合付款",
            "parts": [
                {
                    "account_public_id": opening_acc["public_id"],
                    "account_row_version": opening_acc["row_version"],
                    "component_id": "p_open",
                    "expense_amount_minor": 4000,
                    "account_amount_minor": 4000,
                    "expense_currency_code": "CNY",
                    "account_currency_code": "CNY",
                    "included_in_opening": True,
                },
                {
                    "account_public_id": live_acc["public_id"],
                    "account_row_version": live_acc["row_version"],
                    "component_id": "p_live",
                    "expense_amount_minor": 6000,
                    "account_amount_minor": 6000,
                    "expense_currency_code": "CNY",
                    "account_currency_code": "CNY",
                    "included_in_opening": False,
                },
            ],
        },
    )
    assert funded.status_code == 200, funded.text
    funded_version = funded.json()["expense_row_version"]

    rev = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "reversal",
            "accounting_date": "2026-05-12",
            "reason": "全额冲正",
            "expected_row_version": funded_version,
        },
    )
    assert rev.status_code == 201, rev.text
    offset = rev.json()["active_offsets"][0]

    with SessionLocal() as db:
        row = db.get(Expense, expense["id"])
        assert row is not None
        row.amount_cents = 6000
        row.original_amount_minor = 6000
        db.commit()
        current_version = row.row_version

    blocked_void = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/voids",
        headers=idem(identity.app_headers),
        json={"void_reason": "尝试撤销", "expected_row_version": offset["row_version"]},
    )
    assert blocked_void.status_code == 409, blocked_void.text
    assert blocked_void.json()["error"] == "funding_review_required"

    wrong_repair = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": current_version,
            "reason": "改成其他错误金额",
            "amount_cents": 8000,
            "original_amount_minor": 8000,
        },
    )
    assert wrong_repair.status_code == 409, wrong_repair.text
    assert wrong_repair.json()["error"] == "expense_reversal_active"

    repair = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": current_version,
            "reason": "恢复原付款金额以解除历史不一致",
            "amount_cents": 10000,
            "original_amount_minor": 10000,
        },
    )
    assert repair.status_code == 201, repair.text

    voided = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/voids",
        headers=idem(identity.app_headers),
        json={"void_reason": "核对一致后撤销冲正", "expected_row_version": offset["row_version"]},
    )
    assert voided.status_code == 201, voided.text
    funding_after = client.get(f"/api/expenses/{expense['id']}/funding", headers=identity.app_headers)
    assert funding_after.status_code == 200, funding_after.text
    parts_by_id = {part["component_id"]: part for part in funding_after.json()["parts"]}
    assert parts_by_id["p_open"]["expense_amount_minor"] == 4000
    assert parts_by_id["p_open"]["included_in_opening"] is True
    assert parts_by_id["p_live"]["expense_amount_minor"] == 6000
    assert parts_by_id["p_live"]["included_in_opening"] is False


def test_legacy_reversal_date_drift_blocks_void_until_date_repaired(
    client: TestClient,
    identity,
) -> None:
    bank = _create_account(client, identity, name="日期核对卡", kind="bank")
    expense = manual_confirmed(client, identity, amount_cents=5000)

    funded = client.post(
        f"/api/expenses/{expense['id']}/funding",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "付款",
            "parts": [
                {
                    "account_public_id": bank["public_id"],
                    "account_row_version": bank["row_version"],
                    "component_id": "d1",
                    "expense_amount_minor": 5000,
                    "account_amount_minor": 5000,
                    "expense_currency_code": "CNY",
                    "account_currency_code": "CNY",
                    "included_in_opening": False,
                }
            ],
        },
    )
    assert funded.status_code == 200, funded.text
    rev = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "reversal",
            "accounting_date": "2026-05-12",
            "reason": "冲正",
            "expected_row_version": funded.json()["expense_row_version"],
        },
    )
    assert rev.status_code == 201, rev.text
    offset = rev.json()["active_offsets"][0]

    with SessionLocal() as db:
        row = db.get(Expense, expense["id"])
        assert row is not None
        original_date = row.accounting_date
        row.accounting_date = date(2026, 6, 15)
        db.commit()
        current_version = row.row_version

    blocked = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/voids",
        headers=idem(identity.app_headers),
        json={"void_reason": "日期未修回时撤销", "expected_row_version": offset["row_version"]},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"] == "funding_review_required"

    repaired = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": current_version,
            "reason": "恢复原账务日",
            "time_input": {
                "precision": "date_only",
                "user_local_date": str(original_date),
                "calendar_revision": 1,
            },
        },
    )
    assert repaired.status_code == 201, repaired.text

    voided = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/voids",
        headers=idem(identity.app_headers),
        json={"void_reason": "日期恢复后撤销", "expected_row_version": offset["row_version"]},
    )
    assert voided.status_code == 201, voided.text


def test_legacy_refund_currency_drift_blocks_mixed_currency_comparison(
    client: TestClient,
    identity,
) -> None:
    with SessionLocal() as db:
        db.add(
            ExchangeRate(
                tenant_id="owner",
                home_currency_code="CNY",
                currency_code="USD",
                rate_date=date(2026, 5, 4),
                rate_to_cny=Decimal("7.20000000"),
                source="manual",
            )
        )
        db.add(
            ExchangeRate(
                tenant_id="owner",
                home_currency_code="CNY",
                currency_code="USD",
                rate_date=date(2026, 5, 12),
                rate_to_cny=Decimal("7.20000000"),
                source="manual",
            )
        )
        db.commit()
    expense = manual_confirmed(client, identity, amount_cents=10000)
    with SessionLocal() as db:
        row = db.get(Expense, expense["id"])
        assert row is not None
        row.original_currency_code = "USD"
        row.original_amount_minor = 1000
        row.amount_cents = 7200
        row.exchange_rate_to_cny = Decimal("7.20000000")
        row.exchange_rate_date = date(2026, 5, 4)
        row.exchange_rate_source = "manual"
        db.commit()
        v1 = row.row_version

    refund = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 400,
            "accounting_date": "2026-05-12",
            "reason": "美元部分退款",
            "expected_row_version": v1,
        },
    )
    assert refund.status_code == 201, refund.text

    with SessionLocal() as db:
        row = db.get(Expense, expense["id"])
        assert row is not None
        row.original_currency_code = "JPY"
        row.original_amount_minor = 1000
        db.commit()
        drifted_version = row.row_version

    mixed = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": drifted_version,
            "reason": "在漂移币种下改金额",
            "original_amount_minor": 800,
        },
    )
    assert mixed.status_code == 409, mixed.text
    assert mixed.json()["error"] == "expense_refund_exists"

    mixed_refund = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 100,
            "accounting_date": "2026-05-12",
            "reason": "漂移币种下新增退款",
            "expected_row_version": drifted_version,
        },
    )
    assert mixed_refund.status_code == 409, mixed_refund.text
    assert mixed_refund.json()["error"] == "expense_refund_exists"

    refund_obj = refund.json()["active_offsets"][0]
    mixed_refund_edit = client.post(
        f"/api/expenses/{expense['id']}/offsets/{refund_obj['public_id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "original_amount_minor": 300,
            "accounting_date": "2026-05-12",
            "category": refund_obj["category"],
            "offset_reason": refund_obj["reason"],
            "correction_reason": "漂移币种下更正退款",
            "expected_row_version": refund_obj["row_version"],
        },
    )
    assert mixed_refund_edit.status_code == 409, mixed_refund_edit.text
    assert mixed_refund_edit.json()["error"] == "expense_refund_exists"

    bundle_drifted = client.get(
        f"/api/expenses/{expense['id']}/fact-bundle", headers=identity.app_headers
    )
    assert bundle_drifted.status_code == 200, bundle_drifted.text
    assert bundle_drifted.json()["financial_summary"]["remaining_refundable_original_minor"] == 0
    assert bundle_drifted.json()["financial_summary"]["fx_difference_cents"] == 0

    repaired_usd = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": drifted_version,
            "reason": "修回原美元币种",
            "original_currency_code": "USD",
            "original_amount_minor": 1000,
            "amount_cents": 7200,
        },
    )
    assert repaired_usd.status_code == 201, repaired_usd.text
    bundle_repaired = client.get(
        f"/api/expenses/{expense['id']}/fact-bundle", headers=identity.app_headers
    )
    assert bundle_repaired.status_code == 200, bundle_repaired.text
    assert bundle_repaired.json()["financial_summary"]["remaining_refundable_original_minor"] == 600


def test_all_opening_funded_reversed_expense_drift_blocks_void_until_repaired(
    client: TestClient,
    identity,
) -> None:
    opening_account = client.post(
        "/api/funds/accounts",
        headers=idem(identity.app_headers),
        json={
            "name": "纯期初卡",
            "kind": "bank",
            "currency_code": "CNY",
            "opening_amount_minor": 50000,
            "opening_date": "2026-05-10",
            "opening_source": "核对",
            "visibility": "ledger",
        },
    )
    assert opening_account.status_code == 200, opening_account.text
    opening_acc = opening_account.json()
    expense = manual_confirmed(client, identity, amount_cents=10000)

    funded = client.post(
        f"/api/expenses/{expense['id']}/funding",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "纯期初付款",
            "parts": [
                {
                    "account_public_id": opening_acc["public_id"],
                    "account_row_version": opening_acc["row_version"],
                    "component_id": "open_only",
                    "expense_amount_minor": 10000,
                    "account_amount_minor": 10000,
                    "expense_currency_code": "CNY",
                    "account_currency_code": "CNY",
                    "included_in_opening": True,
                }
            ],
        },
    )
    assert funded.status_code == 200, funded.text
    rev = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "reversal",
            "accounting_date": "2026-05-12",
            "reason": "纯期初冲正",
            "expected_row_version": funded.json()["expense_row_version"],
        },
    )
    assert rev.status_code == 201, rev.text
    offset = rev.json()["active_offsets"][0]

    with SessionLocal() as db:
        row = db.get(Expense, expense["id"])
        assert row is not None
        row.amount_cents = 12000
        row.original_amount_minor = 12000
        row.accounting_date = date(2026, 5, 11)
        db.commit()
        drifted_version = row.row_version

    blocked = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/voids",
        headers=idem(identity.app_headers),
        json={"void_reason": "未修回金额与日期前撤销", "expected_row_version": offset["row_version"]},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"] == "funding_review_required"

    still_bad_date = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": drifted_version,
            "reason": "仅修金额未修日期",
            "amount_cents": 10000,
            "original_amount_minor": 10000,
        },
    )
    assert still_bad_date.status_code == 409, still_bad_date.text
    assert still_bad_date.json()["error"] == "expense_reversal_active"

    repaired = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": drifted_version,
            "reason": "同时恢复原期初付款金额与有效日期",
            "amount_cents": 10000,
            "original_amount_minor": 10000,
            "time_input": {
                "precision": "date_only",
                "user_local_date": "2026-05-10",
                "calendar_revision": 1,
            },
        },
    )
    assert repaired.status_code == 201, repaired.text

    voided = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/voids",
        headers=idem(identity.app_headers),
        json={"void_reason": "修回金额与有效日期后撤销", "expected_row_version": offset["row_version"]},
    )
    assert voided.status_code == 201, voided.text


