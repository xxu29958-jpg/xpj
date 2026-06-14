"""ADR-0049 §2 / §5.1 Debt creation: validate, freeze principal, insert.

Handles external/manual Debt creation only (slice 1). Member-Debt adverse-
interest creation rules (§5.2), bill-split linkage (§4), and any fold-changing
write live in later slices.

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

from decimal import Decimal

from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import FX_STATUS_PENDING
from app.models import Debt
from app.schemas import DebtCreateRequest
from app.services.currency_common import home_currency_code, normalize_currency_code
from app.services.exchange_rate_service import (
    amount_major_to_minor,
    calculate_cny_cents,
    default_rate_date,
    resolve_payload_rate,
)
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


def _clean_principal(value: int | None) -> int:
    if value is None:
        raise AppError("debt_amount_invalid", status_code=422)
    amount = int(value)
    if amount <= 0:
        raise AppError("debt_amount_invalid", status_code=422)
    return amount


def _freeze_money(db: Session, *, tenant_id: str, payload: DebtCreateRequest) -> dict:
    """Resolve the frozen home principal + optional original-currency provenance.

    Home-currency Debt: ``principal_amount_cents`` is the home amount, provenance
    fields stay NULL. Foreign-currency Debt: convert ``original_amount`` in
    ``original_currency`` to home cents via the [[0027]] snapshot for the event
    date and reject if the rate is pending (§2.2). The two inputs are mutually
    exclusive — a request that mixes an explicit home principal with original-
    currency fields is rejected as ambiguous.
    """
    home = home_currency_code()
    has_original = payload.original_currency is not None or payload.original_amount is not None

    if not has_original:
        principal = _clean_principal(payload.principal_amount_cents)
        return {
            "principal_amount_cents": principal,
            "home_currency_code": home,
            "original_currency_code": None,
            "original_amount_minor": None,
            "exchange_rate_to_cny": None,
            "exchange_rate_date": None,
            "exchange_rate_source": None,
        }

    # Foreign-currency path: both original fields required, no client-supplied
    # home principal (the backend computes it).
    if payload.original_currency is None or payload.original_amount is None:
        raise AppError("debt_amount_invalid", status_code=422)
    if payload.principal_amount_cents is not None:
        raise AppError("invalid_request", status_code=422)

    code = normalize_currency_code(payload.original_currency)
    original_amount_minor = amount_major_to_minor(payload.original_amount, code)
    if original_amount_minor is None or original_amount_minor <= 0:
        raise AppError("debt_amount_invalid", status_code=422)
    rate_date = default_rate_date(payload.event_time)

    if code == home:
        # Original currency IS home — no FX, store as a home principal but keep
        # the provenance the client asked for.
        rate: Decimal | None = Decimal("1")
        source: str | None = "base"
        fx_status = "ready"
        effective_date = rate_date
    else:
        rate, source, fx_status, effective_date = resolve_payload_rate(
            db,
            tenant_id=tenant_id,
            currency_code=code,
            rate_date=rate_date,
        )
    if fx_status == FX_STATUS_PENDING:
        # §2.2: cannot freeze a home principal yet — reject rather than commit an
        # un-foldable Debt.
        raise AppError("exchange_rate_pending", status_code=409)

    principal = calculate_cny_cents(
        original_currency_code=code,
        original_amount_minor=original_amount_minor,
        exchange_rate_to_cny=rate,
    )
    if principal is None or principal <= 0:
        raise AppError("debt_amount_invalid", status_code=422)
    return {
        "principal_amount_cents": principal,
        "home_currency_code": home,
        "original_currency_code": code,
        "original_amount_minor": original_amount_minor,
        "exchange_rate_to_cny": rate,
        "exchange_rate_date": effective_date,
        "exchange_rate_source": source,
    }


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
