"""Cross-ADR evidence used by the C02 owner-adoption ceremony."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.app_meta_observation import read_app_meta_value
from app.canonical_money_facts import canonical_money_facts_sha256
from app.canonical_money_facts_contract import INSTALLATION_HOME_CURRENCY_KEY
from app.errors import AppError
from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE, DEFAULT_SUPPORTED_CURRENCY_CODES

_EVIDENCE_SCHEMA = "ticketbox-c02-currency-adoption-evidence-v1"


def _has_legacy_currencyless_money_facts(connection: Connection) -> bool:
    """Detect facts whose released meaning was CNY unless a marker claimed otherwise."""

    return bool(
        connection.scalar(
            text(
                """
                SELECT EXISTS (SELECT 1 FROM budgets)
                    OR EXISTS (SELECT 1 FROM budget_categories)
                    OR EXISTS (
                        SELECT 1 FROM category_rules
                         WHERE amount_min_cents IS NOT NULL
                            OR amount_max_cents IS NOT NULL
                    )
                    OR EXISTS (
                        SELECT 1 FROM csv_import_rows
                         WHERE amount_cents IS NOT NULL
                    )
                    OR EXISTS (
                        SELECT 1 FROM goals
                         WHERE target_amount_cents IS NOT NULL
                    )
                    OR EXISTS (SELECT 1 FROM monthly_income_plans)
                    OR EXISTS (SELECT 1 FROM recurring_items)
                """
            )
        )
    )


@dataclass(frozen=True)
class CurrencyAdoptionEvidence:
    sha256: str
    allowed_home_currency_codes: tuple[str, ...]
    has_conflict: bool


def _json_line(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _resolve_allowed_home_currency_codes(
    explicit_codes: set[str],
    rate_source_codes: set[str],
) -> tuple[tuple[str, ...], bool]:
    has_conflict = any(
        code not in DEFAULT_SUPPORTED_CURRENCY_CODES
        for code in explicit_codes | rate_source_codes
    ) or len(explicit_codes) > 1
    selected = next(iter(explicit_codes), None)
    # ``exchange_rates.rate_to_cny`` is a legacy column name. Released writers
    # stored source-currency -> configured-home rates and rejected source ==
    # home, so a row can eliminate its source code as the historical home but
    # cannot itself prove that the home was CNY.
    if selected is not None and selected in rate_source_codes:
        has_conflict = True
    if has_conflict:
        return (), True
    if selected is not None:
        return (selected,), False
    allowed = tuple(sorted(DEFAULT_SUPPORTED_CURRENCY_CODES - rate_source_codes))
    return allowed, not allowed


def currency_adoption_evidence(connection: Connection) -> CurrencyAdoptionEvidence:
    """Bind legacy facts and derive choices that cannot reinterpret them."""

    digest = hashlib.sha256()
    digest.update((_EVIDENCE_SCHEMA + "\n").encode())
    digest.update(
        _json_line(
            {"c07_money_facts_sha256": canonical_money_facts_sha256(connection)}
        )
    )
    exchange_rows = list(
        connection.execute(
            text(
                """
                SELECT public_id, tenant_id, currency_code, rate_date, rate_to_cny, source
                  FROM exchange_rates
                 ORDER BY public_id
                """
            )
        )
    )
    for row in exchange_rows:
        rate = row.rate_to_cny
        if not isinstance(rate, Decimal) or not rate.is_finite() or rate <= 0:
            raise AppError("currency_binding_corrupt", status_code=503)
        digest.update(
            _json_line(
                {
                    "currency_code": row.currency_code,
                    "public_id": row.public_id,
                    "rate_date": row.rate_date.isoformat(),
                    "rate_to_cny": format(rate, "f"),
                    "source": row.source,
                    "tenant_id": row.tenant_id,
                }
            )
        )
    rate_source_codes = {str(row.currency_code) for row in exchange_rows}

    explicit_codes = set(
        connection.scalars(
            text(
                """
                SELECT home_currency_code FROM expenses
                UNION SELECT home_currency_code FROM debts
                UNION SELECT home_currency_code FROM member_repayment_proposals
                UNION SELECT home_currency_code FROM repayment_drafts
                UNION SELECT home_currency_code FROM bill_split_invitations
                """
            )
        )
    )
    marker = read_app_meta_value(connection, INSTALLATION_HOME_CURRENCY_KEY)
    if marker is not None:
        explicit_codes.add(marker)
    elif _has_legacy_currencyless_money_facts(connection):
        # Before the persisted binding existed, these tables had no per-row
        # currency carrier. The released bridge treated an unmarked legacy
        # installation as CNY and rejected non-CNY reinterpretation. Preserve
        # that historical meaning; an explicit non-CNY fact now becomes a
        # conflict instead of silently relabelling the currencyless facts.
        explicit_codes.add(DEFAULT_HOME_CURRENCY_CODE)
    allowed, has_conflict = _resolve_allowed_home_currency_codes(
        explicit_codes,
        rate_source_codes,
    )
    return CurrencyAdoptionEvidence(
        sha256=digest.hexdigest(),
        allowed_home_currency_codes=allowed,
        has_conflict=has_conflict,
    )


def currency_adoption_evidence_sha256(connection: Connection) -> str:
    return currency_adoption_evidence(connection).sha256
