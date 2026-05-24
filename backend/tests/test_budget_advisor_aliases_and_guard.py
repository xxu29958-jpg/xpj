"""v1.1 PR-2: alias map roundtrip + outbound payload schema guard.

Locks in two ADR-0036 invariants:

- Real PII never appears in an outbound payload — the guard rejects any
  key outside the allowed list (confirmation #1 in ADR-0036).
- The local alias maps round-trip ("snake-eating-tail"): an AI response
  referencing ``merchant_001`` resolves back to the real canonical name
  the user knows (confirmation #2).
"""

from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.errors import DataIntegrityError
from app.models import Account, Ledger
from app.services.budget_advisor_service import (
    BudgetInputs,
    CategorySnapshot,
    MemberRef,
    MerchantSummary,
    assign_transaction_temp_id,
    cleanup_session,
    get_or_create_member_anon,
    get_or_create_merchant_anon,
    resolve_member_anon,
    resolve_merchant_anon,
    resolve_transaction_temp_id,
    to_outbound_dict,
    validate_outbound_payload,
)
from app.services.time_service import now_utc


def _make_extra_ledger(label: str) -> tuple[str, int]:
    """Create an extra ledger + account inside the identity-seeded DB,
    return (ledger_id, account_id)."""
    with SessionLocal() as db:
        now = now_utc()
        account = Account(display_name=f"alias-test-{label}", created_at=now)
        db.add(account)
        db.flush()
        ledger = Ledger(
            ledger_id=f"alias_{label}",
            name=f"alias {label}",
            owner_account_id=account.id,
            created_at=now,
        )
        db.add(ledger)
        db.commit()
        return ledger.ledger_id, account.id


# ---------------------------------------------------------------------------
# outbound payload guard
# ---------------------------------------------------------------------------


def _full_inputs() -> BudgetInputs:
    return BudgetInputs(
        month="2026-05",
        home_currency="CNY",
        members=[MemberRef(anon_id="member_1")],
        category_breakdown=[
            CategorySnapshot(category="餐饮", amount_cents=120000, count=18)
        ],
        merchant_summary=[
            MerchantSummary(
                anon_id="merchant_001",
                category_class="餐饮",
                amount_cents=42000,
                count=6,
            )
        ],
    )


def test_to_outbound_dict_only_contains_allowed_top_level_keys() -> None:
    payload = to_outbound_dict(_full_inputs())
    # The allowed set is the contract — exact match (no extras, nothing missing).
    assert set(payload.keys()) == {
        "month",
        "home_currency",
        "members",
        "category_breakdown",
        "merchant_summary",
        "income_plan",
        "fixed_expenses",
        "historical_baseline",
    }


def test_to_outbound_dict_member_rows_have_only_anon_id() -> None:
    payload = to_outbound_dict(_full_inputs())
    for row in payload["members"]:
        assert set(row.keys()) == {"anon_id"}
        # No real account_id / display_name leaks.
        assert "account_id" not in row
        assert "display_name" not in row


def test_to_outbound_dict_merchant_rows_carry_only_anon_id_no_real_name() -> None:
    payload = to_outbound_dict(_full_inputs())
    for row in payload["merchant_summary"]:
        assert set(row.keys()) == {"anon_id", "category_class", "amount_cents", "count"}
        # The opaque id, never the real merchant canonical.
        assert row["anon_id"].startswith("merchant_")
        assert "merchant_canonical" not in row
        assert "merchant" not in row


def test_validate_rejects_unknown_top_level_key() -> None:
    bad = {
        "month": "2026-05",
        "home_currency": "CNY",
        "members": [],
        "category_breakdown": [],
        "merchant_summary": [],
        "income_plan": [],
        "fixed_expenses": [],
        "historical_baseline": [],
        "evil_extra": "leaked",
    }
    with pytest.raises(DataIntegrityError, match="evil_extra"):
        validate_outbound_payload(bad)


def test_validate_rejects_unknown_row_key() -> None:
    bad = {
        "month": "2026-05",
        "home_currency": "CNY",
        "members": [],
        "category_breakdown": [
            {
                "category": "餐饮",
                "amount_cents": 100,
                "count": 1,
                "merchant_canonical": "麦当劳",  # ← leaks real name
            }
        ],
        "merchant_summary": [],
        "income_plan": [],
        "fixed_expenses": [],
        "historical_baseline": [],
    }
    with pytest.raises(DataIntegrityError, match="merchant_canonical"):
        validate_outbound_payload(bad)


def test_validate_rejects_non_list_row_collection() -> None:
    bad = {
        "month": "2026-05",
        "home_currency": "CNY",
        "members": "should be a list",
        "category_breakdown": [],
        "merchant_summary": [],
        "income_plan": [],
        "fixed_expenses": [],
        "historical_baseline": [],
    }
    with pytest.raises(DataIntegrityError, match="must be a list"):
        validate_outbound_payload(bad)


def test_validate_rejects_non_dict_inputs() -> None:
    with pytest.raises(DataIntegrityError):
        validate_outbound_payload("not a dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# alias roundtrip
# ---------------------------------------------------------------------------


def test_merchant_anon_is_stable_within_tenant(identity) -> None:
    tenant_id = "owner"
    with SessionLocal() as db:
        a = get_or_create_merchant_anon(
            db, tenant_id=tenant_id, merchant_canonical="麦当劳"
        )
        db.commit()
        b = get_or_create_merchant_anon(
            db, tenant_id=tenant_id, merchant_canonical="麦当劳"
        )
        assert a == b == "merchant_001"
        c = get_or_create_merchant_anon(
            db, tenant_id=tenant_id, merchant_canonical="星巴克"
        )
        db.commit()
        assert c == "merchant_002"
        assert (
            resolve_merchant_anon(db, tenant_id=tenant_id, anon_id="merchant_001")
            == "麦当劳"
        )


def test_member_anon_is_stable_per_account(identity) -> None:
    tenant_id = "owner"
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        a = get_or_create_member_anon(
            db, tenant_id=tenant_id, account_id=owner.id
        )
        db.commit()
        b = get_or_create_member_anon(
            db, tenant_id=tenant_id, account_id=owner.id
        )
        assert a == b == "member_1"
        assert (
            resolve_member_anon(db, tenant_id=tenant_id, anon_id="member_1")
            == owner.id
        )


def test_transaction_temp_id_is_session_scoped(identity) -> None:
    tenant_id = "owner"
    s1 = "session-alpha"
    s2 = "session-beta"
    with SessionLocal() as db:
        assign_transaction_temp_id(
            db, tenant_id=tenant_id, expense_id=10, session_id=s1
        )
        assign_transaction_temp_id(
            db, tenant_id=tenant_id, expense_id=11, session_id=s1
        )
        db.commit()
        beta_temp = assign_transaction_temp_id(
            db, tenant_id=tenant_id, expense_id=10, session_id=s2
        )
        db.commit()
        assert beta_temp == "tx_001"
        assert (
            resolve_transaction_temp_id(
                db, tenant_id=tenant_id, session_id=s1, temp_id="tx_001"
            )
            == 10
        )
        removed = cleanup_session(db, tenant_id=tenant_id, session_id=s1)
        db.commit()
        assert removed == 2
        assert (
            resolve_transaction_temp_id(
                db, tenant_id=tenant_id, session_id=s2, temp_id="tx_001"
            )
            == 10
        )


def test_aliases_are_tenant_isolated(identity) -> None:
    tenant_a = "owner"
    tenant_b, _account_b = _make_extra_ledger("isolation_b")
    with SessionLocal() as db_a:
        a_id = get_or_create_merchant_anon(
            db_a, tenant_id=tenant_a, merchant_canonical="麦当劳"
        )
        db_a.commit()
        assert a_id == "merchant_001"
    with SessionLocal() as db_b:
        b_id = get_or_create_merchant_anon(
            db_b, tenant_id=tenant_b, merchant_canonical="麦当劳"
        )
        db_b.commit()
        # Same canonical name, different tenant → independent counter, but
        # the placeholder still starts at _001 because the tenants share
        # no rows.
        assert b_id == "merchant_001"
