"""ADR-0049 P3b / ⑤c-1: cross-ledger member-Debt receivables ("money owed to me").

`GET /api/debts/receivables` (account-scoped, NOT ledger-scoped) lists the member
Debts the authenticated account is the cross-ledger CREDITOR of — the receivable a
bill_split sender cannot see via the ledger-scoped `GET /api/debts` (the Debt lives
in the debtor's ledger). Each row is shell-redacted (`ledger_id=None`, §5.2/ADR-0029)
and carries the DEBTOR's display name in `counterparty_label` so the creditor sees WHO
owes them; `counterparty_account_id`/`direction` stay owner-relative so the row is
byte-identical to the detail framing (list↔detail consistency). The same debtor-name
enrichment is mirrored in `get_participant_debt_response` for the cross-ledger creditor.

Debts are seeded via `create_bill_split_debt` (the canonical §4 entry), so the rollout
flag is irrelevant here.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Debt, Ledger, LedgerMember, Repayment
from app.services.debt_service import (
    create_bill_split_debt,
    get_participant_debt_response,
    list_member_receivables_for_account,
)
from app.services.time_service import now_utc


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        return owner.id


def _seed_account(display_name: str) -> int:
    """A bare account (no ledger) — a valid FK target for a Debt owner/counterparty."""
    with SessionLocal() as db:
        account = Account(display_name=display_name)
        db.add(account)
        db.commit()
        return account.id


def _seed_account_with_ledger(display_name: str, ledger_id: str) -> int:
    """An account that owns its own personal ledger (the creditor is NOT a member of it)."""
    with SessionLocal() as db:
        account = Account(display_name=display_name)
        db.add(account)
        db.flush()
        db.add(Ledger(ledger_id=ledger_id, name=f"{display_name} 的账本", owner_account_id=account.id))
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role="owner"))
        db.commit()
        return account.id


def _seed_receivable(
    *, creditor_id: int, debtor_id: int, debtor_ledger: str, amount_cents: int = 2500
) -> str:
    """Seed the receiver-side member Debt (debtor owes creditor) via the canonical §4 entry.

    owner = debtor, member counterparty = creditor, direction i_owe — exactly what an
    accepted bill split produces. Returns the Debt public_id.
    """
    with SessionLocal() as db:
        debt = create_bill_split_debt(
            db,
            ledger_id=debtor_ledger,
            receiver_account_id=debtor_id,
            sender_account_id=creditor_id,
            amount_cents=amount_cents,
            home_currency_code="CNY",
            source_invitation_public_id=str(uuid4()),
            event_time=None,
        )
        db.commit()
        return debt.public_id


def _receivables_for(account_id: int) -> list:
    with SessionLocal() as db:
        return list(list_member_receivables_for_account(db, account_id=account_id).items)


def test_receivables_endpoint_names_debtor_redacts_ledger(client: TestClient, *, identity) -> None:
    # The core gap-fill: the creditor (owner) sees the cross-ledger member Debt owed to
    # them, named with the DEBTOR's display name, ledger redacted, framed as a receivable.
    owner_id = _owner_account_id()
    debtor_id = _seed_account_with_ledger("阿明", "receiver_b")
    public_id = _seed_receivable(creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="receiver_b")

    resp = client.get("/api/debts/receivables", headers=identity.app_headers)
    assert resp.status_code == 200, resp.json()
    items = resp.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["public_id"] == public_id
    assert row["counterparty_label"] == "阿明"  # the DEBTOR's name — who owes the creditor
    assert row["ledger_id"] is None  # §5.2/ADR-0029 redaction
    assert row["viewer_is_debtor"] is False  # the viewer is the creditor
    assert row["direction"] == "i_owe"  # stored, owner-relative, untouched
    assert row["counterparty_type"] == "member"
    assert row["principal_amount_cents"] == 2500
    assert row["source_type"] == "bill_split"


def test_receivables_name_fallback_when_display_name_blank(client: TestClient, *, identity) -> None:
    # A blank display name leaves counterparty_label None so the renderers fall back to the
    # generic member label (graceful degrade; display_name is NOT NULL so this is rare).
    owner_id = _owner_account_id()
    debtor_id = _seed_account_with_ledger("   ", "receiver_blank")  # whitespace-only name
    _seed_receivable(creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="receiver_blank")

    rows = _receivables_for(owner_id)
    assert len(rows) == 1
    assert rows[0].counterparty_label is None


def test_receivables_excludes_same_ledger_member_debt(client: TestClient, *, identity) -> None:
    # De-dup: a member Debt whose ledger the creditor IS a member of already shows in the
    # creditor's ledger-scoped list_debts, so it must NOT also appear in receivables.
    owner_id = _owner_account_id()
    debtor_id = _seed_account("同账本债务人")
    # Debt parked in the OWNER's own ledger (owner is a member) → excluded from receivables.
    _seed_receivable(creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="owner")

    assert _receivables_for(owner_id) == []


def test_receivables_excludes_payable_owed_to_me_member(client: TestClient, *, identity) -> None:
    # Robustness: a member Debt with direction='owed_to_me' makes the counterparty the
    # DEBTOR (a payable, "I owe"), not a receivable — the direction='i_owe' filter excludes
    # it even though counterparty==viewer and it is cross-ledger.
    owner_id = _owner_account_id()
    debtor_id = _seed_account_with_ledger("反向", "receiver_rev")
    with SessionLocal() as db:
        now = now_utc()
        db.add(
            Debt(
                tenant_id="receiver_rev",
                owner_account_id=debtor_id,
                created_by_account_id=debtor_id,
                direction="owed_to_me",  # counterparty (owner_id) is the DEBTOR here
                counterparty_type="member",
                counterparty_account_id=owner_id,
                counterparty_label=None,
                status="open",
                source_type="bill_split",
                source_id=str(uuid4()),
                principal_amount_cents=2500,
                home_currency_code="CNY",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    assert _receivables_for(owner_id) == []


def test_receivables_excludes_external_debt(client: TestClient, *, identity) -> None:
    # An external Debt has no member counterparty (counterparty_account_id is None per
    # ck_debts_member_has_account), so the counterparty_account_id==viewer clause already
    # excludes it — the counterparty_type=='member' filter is belt-and-suspenders here.
    owner_id = _owner_account_id()
    with SessionLocal() as db:
        now = now_utc()
        db.add(
            Debt(
                tenant_id="owner",
                owner_account_id=owner_id,
                created_by_account_id=owner_id,
                direction="owed_to_me",
                counterparty_type="external",
                counterparty_account_id=None,
                counterparty_label="某商家",
                status="open",
                source_type="manual",
                source_id=None,
                principal_amount_cents=2500,
                home_currency_code="CNY",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    assert _receivables_for(owner_id) == []


def test_receivables_excludes_debtor_view(client: TestClient, *, identity) -> None:
    # The DEBTOR listing their receivables sees nothing: the Debt's counterparty is the
    # creditor, not the debtor, so the debtor is never the counterparty-creditor of it.
    owner_id = _owner_account_id()
    debtor_id = _seed_account_with_ledger("债务人视角", "receiver_dv")
    _seed_receivable(creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="receiver_dv")

    assert _receivables_for(debtor_id) == []


def test_receivables_requires_auth(client: TestClient) -> None:
    assert client.get("/api/debts/receivables").status_code == 401


def test_receivables_detail_matches_list_for_creditor(client: TestClient, *, identity) -> None:
    # list↔detail consistency: the cross-ledger creditor's detail (GET /api/debts/{id}) shows
    # the SAME debtor name + redaction as the receivables list, not the generic member label.
    owner_id = _owner_account_id()
    debtor_id = _seed_account_with_ledger("一致", "receiver_consistent")
    public_id = _seed_receivable(
        creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="receiver_consistent"
    )

    list_resp = client.get("/api/debts/receivables", headers=identity.app_headers)
    list_row = list_resp.json()["items"][0]
    detail = client.get(f"/api/debts/{public_id}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    detail_row = detail.json()
    assert detail_row["counterparty_label"] == list_row["counterparty_label"] == "一致"
    assert detail_row["ledger_id"] is None
    assert detail_row["viewer_is_debtor"] is False


def test_participant_detail_for_same_ledger_debtor_stays_generic(
    client: TestClient, *, identity
) -> None:
    # The DEBTOR's own SAME-LEDGER detail view: the enrichment block (`if not is_ledger_member`)
    # never fires, so the ledger id is kept and counterparty stays generic (the counterparty
    # there is the creditor, framed by the communal headline, not named).
    owner_id = _owner_account_id()
    debtor_id = _seed_account_with_ledger("自视", "receiver_self")
    public_id = _seed_receivable(creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="receiver_self")

    with SessionLocal() as db:
        response = get_participant_debt_response(
            db, public_id=public_id, ledger_id="receiver_self", account_id=debtor_id
        )
    assert response.viewer_is_debtor is True
    assert response.counterparty_label is None  # stays generic for the debtor's own view
    assert response.ledger_id == "receiver_self"  # same-ledger → not redacted


def test_participant_detail_for_cross_ledger_debtor_stays_generic(
    client: TestClient, *, identity
) -> None:
    # The creditor-only enrichment guard: a CROSS-LEDGER DEBTOR (owed_to_me member Debt where the
    # viewer is the counterparty-debtor) reaches the redaction branch but must NOT be enriched
    # with the creditor's name — only viewer_is_debtor==False (the creditor) is named. Removing
    # the `viewer_is_debtor is False` guard would wrongly leak the creditor's name to the debtor.
    owner_id = _owner_account_id()  # the test owner acts as the cross-ledger DEBTOR here
    creditor_id = _seed_account_with_ledger("外部债权人", "receiver_creditor")
    with SessionLocal() as db:
        now = now_utc()
        debt = Debt(
            tenant_id="receiver_creditor",  # the creditor's ledger; the owner is NOT a member
            owner_account_id=creditor_id,  # owed_to_me → owner is the creditor
            created_by_account_id=creditor_id,
            direction="owed_to_me",
            counterparty_type="member",
            counterparty_account_id=owner_id,  # the counterparty is the DEBTOR (the test owner)
            counterparty_label=None,
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
            principal_amount_cents=2500,
            home_currency_code="CNY",
            created_at=now,
            updated_at=now,
        )
        db.add(debt)
        db.commit()
        public_id = debt.public_id

    with SessionLocal() as db:
        response = get_participant_debt_response(
            db, public_id=public_id, ledger_id="owner", account_id=owner_id
        )
    assert response.viewer_is_debtor is True  # the viewer is the debtor of this payable
    assert response.ledger_id is None  # cross-ledger → redacted
    assert response.counterparty_label is None  # NOT enriched — the debtor is not named the creditor


def test_participant_detail_for_cross_ledger_creditor_is_enriched(
    client: TestClient, *, identity
) -> None:
    # Direct service-level pin of the creditor-IS-enriched detail branch (mirrors the two
    # debtor detail tests): cross-ledger creditor → ledger redacted, viewer_is_debtor False,
    # counterparty_label = the debtor's name. Removing the enrichment leaves the label None.
    owner_id = _owner_account_id()
    debtor_id = _seed_account_with_ledger("被看见", "receiver_cred")
    public_id = _seed_receivable(creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="receiver_cred")

    with SessionLocal() as db:
        response = get_participant_debt_response(
            db, public_id=public_id, ledger_id="owner", account_id=owner_id
        )
    assert response.viewer_is_debtor is False
    assert response.ledger_id is None
    assert response.counterparty_label == "被看见"


def test_receivables_includes_soft_removed_creditor_receivable(
    client: TestClient, *, identity
) -> None:
    # A creditor SOFT-REMOVED (disabled_at) from the debtor's ledger cannot get a token for
    # it, so cannot see the Debt via list_debts — the dedup must use ACTIVE membership so the
    # receivable stays visible. Mutation: dropping the disabled_at filter counts the stale
    # membership and wrongly hides this receivable.
    owner_id = _owner_account_id()
    debtor_id = _seed_account_with_ledger("阿明", "receiver_b")
    public_id = _seed_receivable(creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="receiver_b")
    with SessionLocal() as db:
        db.add(
            LedgerMember(
                ledger_id="receiver_b",
                account_id=owner_id,
                role="member",
                disabled_at=now_utc(),  # soft-removed: cannot obtain a token for this ledger
            )
        )
        db.commit()

    rows = _receivables_for(owner_id)
    assert [r.public_id for r in rows] == [public_id]  # still visible despite the disabled row


def test_receivables_names_each_debtor_in_multi_row(client: TestClient, *, identity) -> None:
    # Two cross-ledger receivables from two distinct debtors: each row carries the CORRECT
    # debtor's name keyed by owner — pins the batched _owner_display_names mapping (a mutation
    # that mis-keys or reuses one name for all rows would fail).
    owner_id = _owner_account_id()
    ming = _seed_account_with_ledger("阿明", "receiver_b")
    hong = _seed_account_with_ledger("小红", "receiver_c")
    pid_ming = _seed_receivable(creditor_id=owner_id, debtor_id=ming, debtor_ledger="receiver_b")
    pid_hong = _seed_receivable(creditor_id=owner_id, debtor_id=hong, debtor_ledger="receiver_c")

    rows = _receivables_for(owner_id)
    assert {r.public_id: r.counterparty_label for r in rows} == {
        pid_ming: "阿明",
        pid_hong: "小红",
    }


def test_receivables_includes_cleared_receivable(client: TestClient, *, identity) -> None:
    # No status filter: a fully-repaid (cleared) receivable still lists, with derived status
    # 'cleared'. A full Repayment fact drives the fold to 0 and the stored status is latched
    # cleared (as lock_and_fold would). Mutation adding `.where(Debt.status=='open')` drops
    # settled history and fails this.
    owner_id = _owner_account_id()
    debtor_id = _seed_account_with_ledger("已清", "receiver_cleared")
    public_id = _seed_receivable(creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="receiver_cleared")
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
        db.add(
            Repayment(
                debt_id=debt.id,
                amount_cents=debt.principal_amount_cents,  # full repayment → remaining 0
                paid_at=now_utc(),
                actor_account_id=debtor_id,
                idempotency_key=str(uuid4()),
            )
        )
        debt.status = "cleared"  # the latch a fold-changing write persists
        db.commit()

    rows = _receivables_for(owner_id)
    assert len(rows) == 1
    assert rows[0].public_id == public_id
    assert rows[0].status == "cleared"
    assert rows[0].remaining_amount_cents == 0
