"""Family role + identity (ledgers / ledger_members) integrity checks."""

from __future__ import annotations

from sqlalchemy import text

from app.errors import DataIntegrityError


def _validate_family_role_data(connection, table_names: set[str]) -> None:
    """Reject legacy SQLite rows that would bypass role CHECK constraints.

    SQLite cannot add CHECK constraints to an existing table with ALTER TABLE.
    Older valid databases stay compatible; malformed rows fail fast on startup
    instead of producing undefined permission behavior.
    """

    if "ledger_members" in table_names:
        invalid_members = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM ledger_members "
                    "WHERE role IS NULL OR role NOT IN ('owner', 'member', 'viewer')"
                )
            ).scalar_one()
        )
        if invalid_members:
            raise DataIntegrityError("Invalid legacy data: ledger_members.role contains unsupported values")
    if "invitations" in table_names:
        invalid_invitations = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM invitations "
                    "WHERE role IS NULL OR role NOT IN ('member', 'viewer')"
                )
            ).scalar_one()
        )
        if invalid_invitations:
            raise DataIntegrityError("Invalid legacy data: invitations.role contains unsupported values")
    if "auth_tokens" in table_names:
        invalid_auth_scopes = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM auth_tokens "
                    "WHERE scope IS NULL OR scope NOT IN ('app', 'admin')"
                )
            ).scalar_one()
        )
        if invalid_auth_scopes:
            raise DataIntegrityError("Invalid legacy data: auth_tokens.scope contains unsupported values")


def _validate_identity_unique_scopes(connection, table_names: set[str]) -> None:
    """Reject legacy identity rows that cannot satisfy current parent keys."""

    if "ledgers" in table_names:
        duplicate_ledger = connection.execute(
            text(
                "SELECT ledger_id, COUNT(*) AS count "
                "FROM ledgers "
                "GROUP BY ledger_id "
                "HAVING COUNT(*) > 1 "
                "LIMIT 1"
            )
        ).mappings().first()
        if duplicate_ledger is not None:
            raise DataIntegrityError(
                "Invalid legacy data: ledgers contains duplicate ledger_id rows "
                f"for ledger_id={duplicate_ledger['ledger_id']}"
            )

    if "ledger_members" in table_names:
        duplicate_member = connection.execute(
            text(
                "SELECT ledger_id, account_id, COUNT(*) AS count "
                "FROM ledger_members "
                "GROUP BY ledger_id, account_id "
                "HAVING COUNT(*) > 1 "
                "LIMIT 1"
            )
        ).mappings().first()
        if duplicate_member is not None:
            raise DataIntegrityError(
                "Invalid legacy data: ledger_members contains duplicate ledger/account rows "
                f"for ledger_id={duplicate_member['ledger_id']} account_id={duplicate_member['account_id']}"
            )
