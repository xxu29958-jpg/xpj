"""Stable product protocol for runtime compatibility negotiation.

The public contract intentionally contains no database migration name,
Alembic revision, installer receipt, or release-internal state.  Clients bind
their write intent to the product API version and the persisted installation
currency contract they observed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RUNTIME_COMPATIBILITY_CONTRACT = "ticketbox-runtime-compatibility-v1"
CURRENT_API_VERSION = "2026-08-02"

# RFC 6648 discourages new ``X-`` names.  The application prefix keeps these
# limited-use fields unambiguous, as recommended for new HTTP fields by RFC
# 9110 section 16.3.2.1.
TICKETBOX_API_VERSION_HEADER = "Ticketbox-Api-Version"
TICKETBOX_CURRENCY_BINDING_HEADER = "Ticketbox-Currency-Binding"

RUNTIME_COMPATIBILITY_SESSION_KEY = "ticketbox.runtime_compatibility_request"

_CURRENCY_BINDING_PATTERN = re.compile(
    r"^(?P<contract_version>[1-9][0-9]*):"
    r"(?P<binding_revision>0|[1-9][0-9]*):"
    r"(?P<home_currency_code>[A-Z]{3})$"
)


@dataclass(frozen=True)
class RuntimeCompatibilityRequest:
    """Raw request negotiation fields attached to one SQLAlchemy Session."""

    api_version: str | None
    currency_binding: str | None
    origin: Literal["http_client", "server_runtime"] = "http_client"

    @property
    def is_legacy(self) -> bool:
        return (
            self.origin == "http_client"
            and self.api_version is None
            and self.currency_binding is None
        )


def parse_currency_binding(value: str) -> tuple[int, int, str]:
    """Parse ``<contract-version>:<revision>:<home-currency>`` strictly.

    The currency is part of the proof even at revision zero.  Otherwise two
    different EMPTY-installation offers would share the same token and a
    configuration change between discovery and the first write could silently
    reinterpret the client's minor units.
    """

    match = _CURRENCY_BINDING_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError("invalid Ticketbox-Currency-Binding")
    return (
        int(match.group("contract_version")),
        int(match.group("binding_revision")),
        match.group("home_currency_code"),
    )


def format_currency_binding(
    *,
    contract_version: int,
    binding_revision: int,
    home_currency_code: str,
) -> str:
    if (
        contract_version < 1
        or binding_revision < 0
        or re.fullmatch(r"[A-Z]{3}", home_currency_code) is None
    ):
        raise ValueError("currency binding components are outside the product contract")
    return f"{contract_version}:{binding_revision}:{home_currency_code}"


__all__ = [
    "CURRENT_API_VERSION",
    "RUNTIME_COMPATIBILITY_CONTRACT",
    "RUNTIME_COMPATIBILITY_SESSION_KEY",
    "RuntimeCompatibilityRequest",
    "TICKETBOX_API_VERSION_HEADER",
    "TICKETBOX_CURRENCY_BINDING_HEADER",
    "format_currency_binding",
    "parse_currency_binding",
]
