"""Closed loopback PostgreSQL URL validation for installed maintenance roles."""

from __future__ import annotations

import ipaddress

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class ManagedPostgresUrlError(RuntimeError):
    """An installed PostgreSQL URL escaped its declared role contract."""


def validated_local_role_url(
    database_url: str,
    *,
    database_name: str,
    role: str,
    purpose: str,
) -> URL:
    if not isinstance(database_url, str) or not database_url:
        raise ManagedPostgresUrlError(f"{purpose} database URL must be explicit")
    try:
        parsed = make_url(database_url)
    except ArgumentError as exc:
        raise ManagedPostgresUrlError(f"{purpose} database URL is invalid") from exc
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ManagedPostgresUrlError(f"{purpose} requires PostgreSQL psycopg")
    if (
        parsed.username != role
        or parsed.password is not None
        or parsed.database != database_name
        or parsed.host is None
        or parsed.port is None
        or not 1 <= parsed.port <= 65535
        or set(parsed.query) != {"require_auth"}
        or parsed.query.get("require_auth") != "scram-sha-256"
    ):
        raise ManagedPostgresUrlError(f"{purpose} database URL violates its role contract")
    try:
        address = ipaddress.ip_address(parsed.host)
    except ValueError as exc:
        raise ManagedPostgresUrlError(f"{purpose} host must be a loopback IP literal") from exc
    if not address.is_loopback:
        raise ManagedPostgresUrlError(f"{purpose} host must be loopback")
    return parsed.set(drivername="postgresql+psycopg")


__all__ = ["ManagedPostgresUrlError", "validated_local_role_url"]
