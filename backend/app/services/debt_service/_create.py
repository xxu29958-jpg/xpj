"""ADR-0049 §2 / §5.1 Debt creation: validate, freeze principal, insert.

Handles public external/manual Debt creation only (slice 1). Member-Debt
adverse-interest creation rules (§5.2), bill-split linkage (§4), and any
fold-changing write live in later slices.

Currency (§2.2): a home-currency Debt stores ``principal_amount_cents`` directly.
A foreign-currency Debt freezes a backend-authoritative home principal from the
[[0027]] snapshot (``resolve_payload_rate`` + ``calculate_cny_cents``); if the
rate is still pending the create is rejected with ``exchange_rate_pending`` (409)
rather than committing an un-foldable Debt. Clients never submit rates or compute
home amounts.

Request idempotency ([[0042]]) is handled by the route via
``claim_idempotent_request`` — this service does not define a second mechanism.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Debt
from app.schemas import DebtCreateRequest
from app.services.debt_service._money import freeze_home_amount
from app.services.time_service import now_utc

VALID_DIRECTIONS = frozenset({"i_owe", "owed_to_me"})
VALID_COUNTERPARTY_TYPES = frozenset({"member", "external"})
VALID_SOURCE_TYPES = frozenset({"manual", "bill_split"})


def _clean_direction(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned not in VALID_DIRECTIONS:
        raise AppError("debt_direction_invalid", status_code=422)
    return cleaned


def _clean_counterparty_type(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned not in VALID_COUNTERPARTY_TYPES:
        raise AppError("debt_counterparty_invalid", status_code=422)
    # Public create cannot commit manual member Debt yet: ADR-0049 §5.2 requires
    # affected-party confirmation before a member obligation becomes committed.
    if cleaned != "external":
        raise AppError("debt_counterparty_invalid", status_code=422)
    return cleaned


def _clean_source_type(value: str | None) -> str:
    cleaned = (value or "manual").strip()
    # Slice 1 only exposes external/manual create; bill_split-sourced Debt is
    # produced server-side by the accept transaction (§4, slice 4), so a client
    # asking for it directly here is rejected.
    if cleaned != "manual":
        raise AppError("invalid_request", status_code=422)
    return cleaned


def _clean_counterparty(
    counterparty_type: str,
    *,
    account_id: int | None,
    label: str | None,
) -> tuple[int | None, str | None]:
    """Member Debt needs an account id; external Debt needs a label (§2 / §5.1)."""
    cleaned_label = (label or "").strip() or None
    if counterparty_type == "member":
        if account_id is None:
            raise AppError("debt_counterparty_invalid", status_code=422)
        # A member counterparty is identified by account, not a free-text label.
        return account_id, None
    # external
    if account_id is not None or cleaned_label is None:
        raise AppError("debt_counterparty_invalid", status_code=422)
    return None, cleaned_label


def _freeze_money(db: Session, *, tenant_id: str, payload: DebtCreateRequest) -> dict:
    """Resolve the frozen home principal + optional original-currency provenance.

    Delegates the home-vs-foreign-currency freeze to the shared
    :func:`~app.services.debt_service._money.freeze_home_amount` (the single
    §2.2 definition slice 2's repayment freeze also uses) and renames the
    home-amount key to the Debt principal column. Behaviour is identical to the
    slice-1 inline version: home-currency principal stored directly; foreign
    converted from the [[0027]] snapshot for the event date and rejected with
    ``exchange_rate_pending`` (409) when pending; mixing an explicit home
    principal with original-currency fields is ``invalid_request``.
    """
    money = freeze_home_amount(
        db,
        tenant_id=tenant_id,
        amount_cents=payload.principal_amount_cents,
        original_currency=payload.original_currency,
        original_amount=payload.original_amount,
        event_time=payload.event_time,
        amount_error="debt_amount_invalid",
    )
    return {"principal_amount_cents": money.pop("amount_cents"), **money}


def create_debt(
    db: Session,
    *,
    tenant_id: str,
    created_by_account_id: int,
    owner_account_id: int,
    payload: DebtCreateRequest,
    commit: bool = True,
) -> Debt:
    """Create one external/manual Debt and return the persisted row.

    ``row_version`` is left at its insert default of 1 — a brand-new Debt is not
    hand-bumped ([[0041]]). ``commit=False`` lets the route commit the insert
    together with the [[0042]] idempotency-success record in one transaction.
    """
    direction = _clean_direction(payload.direction)
    counterparty_type = _clean_counterparty_type(payload.counterparty_type)
    source_type = _clean_source_type(payload.source_type)
    counterparty_account_id, counterparty_label = _clean_counterparty(
        counterparty_type,
        account_id=payload.counterparty_account_id,
        label=payload.counterparty_label,
    )
    money = _freeze_money(db, tenant_id=tenant_id, payload=payload)

    now = now_utc()
    debt = Debt(
        tenant_id=tenant_id,
        owner_account_id=owner_account_id,
        created_by_account_id=created_by_account_id,
        direction=direction,
        counterparty_type=counterparty_type,
        counterparty_account_id=counterparty_account_id,
        counterparty_label=counterparty_label,
        status="open",
        source_type=source_type,
        source_id=None,
        created_at=now,
        updated_at=now,
        **money,
    )
    db.add(debt)
    if commit:
        db.commit()
        db.refresh(debt)
    else:
        db.flush()
    return debt


def create_bill_split_debt(
    db: Session,
    *,
    ledger_id: str,
    receiver_account_id: int,
    sender_account_id: int,
    amount_cents: int,
    source_invitation_public_id: str,
    event_time: datetime | None,
) -> Debt:
    """ADR-0049 §4: insert the receiver-side member Debt for an accepted bill split.

    Called from inside ``bill_split_service.accept_invitation``'s transaction so
    the Debt commits together with the receiver expense and the invited→accepted
    claim — §4 "all three outcomes commit together or none commit". This is the
    ONLY path allowed to create a ``member`` + ``bill_split`` Debt: it bypasses
    the public-create guards (``_clean_counterparty_type`` / ``_clean_source_type``
    reject ``member`` / ``bill_split``) because §5.2 makes it valid — the debtor
    (the receiver) just accepted the invitation.

    The receiver owes ``amount_cents`` — the agreed HOME-currency share, not the
    parent's original-currency total — so the principal freezes as a plain
    home-currency amount (original provenance NULL), mirroring the receiver
    expense ``accept_invitation`` writes. Dedup is the ``uq_debts_source``
    ``(source_type, source_id)`` constraint plus the caller's re-accept fast
    path: a re-accept returns the existing result before reaching here, so no
    second Debt is attempted (§4 "re-accept ... MUST NOT create another Debt").
    ``row_version`` stays at its insert default of 1 ([[0041]]); ``flush`` (not
    ``commit``) lets the accept transaction commit everything atomically.
    """
    money = freeze_home_amount(
        db,
        tenant_id=ledger_id,
        amount_cents=amount_cents,
        original_currency=None,
        original_amount=None,
        event_time=event_time,
        amount_error="debt_amount_invalid",
    )
    now = now_utc()
    debt = Debt(
        tenant_id=ledger_id,
        owner_account_id=receiver_account_id,
        created_by_account_id=receiver_account_id,
        direction="i_owe",
        counterparty_type="member",
        counterparty_account_id=sender_account_id,
        counterparty_label=None,
        status="open",
        source_type="bill_split",
        source_id=source_invitation_public_id,
        principal_amount_cents=money.pop("amount_cents"),
        created_at=now,
        updated_at=now,
        **money,
    )
    db.add(debt)
    db.flush()
    return debt
