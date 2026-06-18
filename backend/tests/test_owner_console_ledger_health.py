"""T26: Owner Console per-ledger health card + slice-5 debt overview aggregates.

The slice-5 owner debt overview extends the ``账本健康`` table with two AGGREGATE
columns — open external debt count + a goal-needs-review integrity flag (warn badge
→ /web/debt-goals). ADR-0049 §7.0 / slice 5 forbid any per-user / per-counterparty /
who-owes-who detail in the owner ops view, so these tests also pin that no
counterparty label leaks into the dashboard.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Account, Debt, DebtGoalLink, Goal, LedgerMember
from app.routes.owner_console import _require_local
from app.services.debt_service import count_open_external_debts
from app.services.goal_debt_repayment_service import ledger_has_goal_needing_review
from app.services.ledger_service import create_ledger


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


# ── ORM seed helpers ──────────────────────────────────────────────────────────


def _owner_account_id(db) -> int:
    owner_account_id = db.scalar(
        select(LedgerMember.account_id)
        .where(LedgerMember.ledger_id == "owner", LedgerMember.role == "owner")
        .limit(1)
    )
    assert owner_account_id is not None
    return owner_account_id


def _seed_debt(
    db,
    *,
    tenant_id: str,
    owner_id: int,
    counterparty_type: str,
    status: str,
    label: str | None = None,
    principal: int = 10000,
) -> Debt:
    """Seed one Debt with a directly-set stored ``status`` (the count reads the latch).

    ``counterparty_type='member'`` mints a counterparty account; ``status`` is written
    straight onto the row so a 'cleared' / 'voided' seed faithfully exercises the
    count's stored-status filter without needing a Repayment / DebtVoid fact.
    """
    member_id = None
    source_type = "manual"
    source_id = None
    if counterparty_type == "member":
        member = Account(display_name=label or "家人")
        db.add(member)
        db.flush()
        member_id = member.id
        source_type = "bill_split"
        source_id = str(uuid4())
    debt = Debt(
        tenant_id=tenant_id,
        owner_account_id=owner_id,
        created_by_account_id=owner_id,
        direction="i_owe",
        counterparty_type=counterparty_type,
        counterparty_account_id=member_id,
        counterparty_label=label,
        principal_amount_cents=principal,
        home_currency_code="CNY",
        status=status,
        source_type=source_type,
        source_id=source_id,
    )
    db.add(debt)
    db.flush()
    return debt


def _seed_debt_goal(db, *, tenant_id: str, owner_id: int, link_status: str, name: str = "清掉欠款") -> Goal:
    """Seed an active debt_repayment goal linking one external Debt with ``link_status``.

    A ``voided`` linked Debt makes the §6/F13 evaluator flag ``needs_review`` (unacked);
    an ``open`` link evaluates to ``in_progress`` (no review).
    """
    goal = Goal(
        tenant_id=tenant_id,
        name=name,
        goal_type="debt_repayment",
        period="monthly",
        status="active",
        goal_version=1,
    )
    db.add(goal)
    db.flush()
    debt = _seed_debt(
        db,
        tenant_id=tenant_id,
        owner_id=owner_id,
        counterparty_type="external",
        status=link_status,
    )
    db.add(DebtGoalLink(goal_id=goal.id, goal_version=1, debt_id=debt.id))
    db.flush()
    return goal


# ── existing health-card coverage ─────────────────────────────────────────────


def test_owner_index_renders_ledger_health_section(local_client: TestClient) -> None:
    body = local_client.get("/owner").text
    assert "账本健康" in body
    assert "/web/data-quality?ledger_id=" in body
    # slice-5 columns are always present (even with no debt data).
    assert "外部欠款" in body
    assert "目标复核" in body


def test_owner_ledger_health_shows_pending_count(local_client: TestClient, *, identity) -> None:
    resp = local_client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=PNG,
    )
    assert resp.status_code == 200
    body = local_client.get("/owner").text
    # The default ledger is "owner"; that row must now show ≥ 1 pending.
    assert "账本健康" in body
    # Quick links scoped per ledger.
    assert 'href="/web?ledger_id=owner"' in body


def test_owner_ledger_health_no_secret_leak(local_client: TestClient, *, identity) -> None:
    body = local_client.get("/owner").text
    assert identity.app_token not in body
    assert identity.admin_token not in body
    assert identity.upload_key not in body


# ── slice-5: count_open_external_debts (debt_service aggregate) ────────────────


def test_count_open_external_debts_counts_only_open_external(identity) -> None:
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        # owner ledger: 2 open external (counted) + 1 cleared + 1 voided + 1 open member (all excluded)
        _seed_debt(db, tenant_id="owner", owner_id=owner_id, counterparty_type="external", status="open")
        _seed_debt(db, tenant_id="owner", owner_id=owner_id, counterparty_type="external", status="open")
        _seed_debt(db, tenant_id="owner", owner_id=owner_id, counterparty_type="external", status="cleared")
        _seed_debt(db, tenant_id="owner", owner_id=owner_id, counterparty_type="external", status="voided")
        _seed_debt(db, tenant_id="owner", owner_id=owner_id, counterparty_type="member", status="open")
        # a second owner-managed ledger with 1 open external proves per-tenant grouping + isolation
        other = create_ledger(db, account_id=owner_id, name="第二本")
        _seed_debt(db, tenant_id=other.ledger_id, owner_id=owner_id, counterparty_type="external", status="open")
        db.flush()
        counts = count_open_external_debts(db, ["owner", other.ledger_id])
    assert counts == {"owner": 2, other.ledger_id: 1}


def test_count_open_external_debts_empty_tenants_returns_empty(identity) -> None:
    with SessionLocal() as db:
        assert count_open_external_debts(db, []) == {}


# ── slice-5: ledger_has_goal_needing_review (goal_service aggregate) ───────────


def test_ledger_has_goal_needing_review_true_on_unacked_voided_link(identity) -> None:
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        _seed_debt_goal(db, tenant_id="owner", owner_id=owner_id, link_status="voided")
        assert ledger_has_goal_needing_review(db, tenant_id="owner") is True


def test_ledger_has_goal_needing_review_false_for_in_progress(identity) -> None:
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        _seed_debt_goal(db, tenant_id="owner", owner_id=owner_id, link_status="open")
        assert ledger_has_goal_needing_review(db, tenant_id="owner") is False


def test_ledger_has_goal_needing_review_false_when_no_goals(identity) -> None:
    with SessionLocal() as db:
        assert ledger_has_goal_needing_review(db, tenant_id="owner") is False


def test_ledger_has_goal_needing_review_isolated_per_tenant(identity) -> None:
    # A voided-link goal in ANOTHER managed ledger must not flag the owner ledger
    # (pins the list_debt_repayment_goals ledger scope — a dropped scope would leak).
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        other = create_ledger(db, account_id=owner_id, name="第二本")
        _seed_debt_goal(db, tenant_id=other.ledger_id, owner_id=owner_id, link_status="voided")
        assert ledger_has_goal_needing_review(db, tenant_id=other.ledger_id) is True
        assert ledger_has_goal_needing_review(db, tenant_id="owner") is False


def test_ledger_has_goal_needing_review_false_for_archived_goal(identity) -> None:
    # An archived debt goal is out of scope for the owner integrity flag, even with a
    # voided link (list_debt_repayment_goals uses include_archived=False).
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        goal = _seed_debt_goal(db, tenant_id="owner", owner_id=owner_id, link_status="voided")
        goal.status = "archived"
        db.flush()
        assert ledger_has_goal_needing_review(db, tenant_id="owner") is False


# ── slice-5: owner index render (count column + warn badge + aggregate-only) ──


def test_owner_ledger_health_shows_open_external_debt_count(local_client: TestClient, *, identity) -> None:
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        for _ in range(3):
            _seed_debt(db, tenant_id="owner", owner_id=owner_id, counterparty_type="external", status="open")
        # excluded shapes must NOT inflate the rendered count
        _seed_debt(db, tenant_id="owner", owner_id=owner_id, counterparty_type="external", status="cleared")
        _seed_debt(db, tenant_id="owner", owner_id=owner_id, counterparty_type="member", status="open")
        # a second managed ledger with a DIFFERENT open-external count proves the
        # per-row .get(ledger_id, 0) mapping in list_ledger_health, not just the
        # underlying grouped query (a key-mapping bug would render 1 on owner's row).
        other = create_ledger(db, account_id=owner_id, name="第二本")
        _seed_debt(db, tenant_id=other.ledger_id, owner_id=owner_id, counterparty_type="external", status="open")
        db.commit()
    body = local_client.get("/owner").text
    # No expenses seeded → every data-quality cell is 0/—, so each non-zero text-end
    # count cell is uniquely one ledger's open-external column.
    assert '<td class="text-end">3</td>' in body  # owner ledger
    assert '<td class="text-end">1</td>' in body  # second ledger, mapped to its own row


def test_owner_ledger_health_goal_review_warn_badge_links_debt_goals(
    local_client: TestClient, *, identity
) -> None:
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        _seed_debt_goal(db, tenant_id="owner", owner_id=owner_id, link_status="voided")
        db.commit()
    body = local_client.get("/owner").text
    assert "需复核" in body
    assert '/web/debt-goals?ledger_id=owner' in body


def test_owner_ledger_health_no_warn_badge_when_goals_clean(
    local_client: TestClient, *, identity
) -> None:
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        _seed_debt_goal(db, tenant_id="owner", owner_id=owner_id, link_status="open")
        db.commit()
    body = local_client.get("/owner").text
    # in_progress goal → no integrity flag → no debt-goals deep-link rendered.
    assert "/web/debt-goals" not in body


def test_owner_ledger_health_aggregate_only_no_counterparty_label(
    local_client: TestClient, *, identity
) -> None:
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        _seed_debt(
            db,
            tenant_id="owner",
            owner_id=owner_id,
            counterparty_type="external",
            status="open",
            label="张三的烧烤店",
        )
        _seed_debt(
            db,
            tenant_id="owner",
            owner_id=owner_id,
            counterparty_type="member",
            status="open",
            label="李四",
        )
        db.commit()
    body = local_client.get("/owner").text
    # Owner ops view is aggregate-only: no who-owes-who / counterparty detail.
    assert "张三的烧烤店" not in body
    assert "李四" not in body
