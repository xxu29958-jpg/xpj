"""Frozen standalone bootstrap from an empty database to the C07 predecessor.

The host coordinator owns roles and the later BIGINT transition.  This physical
file must stay independent of ``app.database`` and the ordinary runtime engine.
"""

from __future__ import annotations

import configparser
import ipaddress
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError, RevisionError
from alembic.util.exc import CommandError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.services.secure_file import hold_protected_file_for_read

FRESH_SOURCE_BOOTSTRAP_RESULT_SCHEMA = "ticketbox-c07-fresh-source-bootstrap-result-v1"
FRESH_SOURCE_BOOTSTRAP_ATTRIBUTE = "ticketbox_c07_fresh_source_bootstrap_v1"
C07_ALEMBIC_PROTOCOL_ATTRIBUTE = "ticketbox_c07_json_protocol_v1"
C07_GRAPH_BASE_REVISION = "20260524_0001"
C07_SOURCE_REVISION = "20260722_0001"
C07_TARGET_REVISION = "20260729_0001"
DATABASE_NAME = "ticketbox"
MIGRATOR_ROLE = "ticketbox_migrator"
SCHEMA_OWNER_ROLE = "ticketbox_owner"

_RESULT_FIELDS = ("schema", "source_revision", "target_revision", "result", "alembic_revision")
_CANONICAL_EMPTY_VERSION_RELATIONS = (("alembic_version", "r"), ("alembic_version_pkc", "i"))
_PGPASS_NAME = re.compile(r"\.ticketbox-pgpass-[1-9][0-9]*-[0-9a-f]{32}\Z")


class C07FreshSourceBootstrapError(RuntimeError):
    """The fresh database cannot safely bootstrap to the C07 source."""


@dataclass(frozen=True)
class FreshSourceAlembicPlan:
    """Graph-proven Alembic configuration for this one release transition."""

    config: Config
    source_revision: str
    target_revision: str


def _backend_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    root_text = str(root)
    if root_text not in sys.path:
        # The baseline revision imports its frozen statement package by the
        # top-level ``migrations`` name.  Add only the root that physically
        # contains this attested action and that package.
        sys.path.insert(0, root_text)
    return root


def _load_frozen_alembic_plan() -> FreshSourceAlembicPlan:
    backend_root = _backend_root()
    ini_path = backend_root / "alembic.ini"
    migrations_path = backend_root / "migrations"
    if not ini_path.is_file() or not (migrations_path / "env.py").is_file():
        raise C07FreshSourceBootstrapError(
            "C07 fresh-source Alembic program is unavailable"
        )

    config = Config(str(ini_path))
    config.attributes[C07_ALEMBIC_PROTOCOL_ATTRIBUTE] = True
    config.set_main_option("script_location", str(migrations_path))
    try:
        scripts = ScriptDirectory.from_config(config)
        bases = tuple(scripts.get_bases())
        heads = tuple(scripts.get_heads())
        source = scripts.get_revision(C07_SOURCE_REVISION)
        target = scripts.get_revision(C07_TARGET_REVISION)
        source_chain = tuple(scripts.iterate_revisions(C07_SOURCE_REVISION, "base"))
    except (
        CommandError, ResolutionError, RevisionError, configparser.Error,
        OSError, KeyError, ValueError,
    ):
        raise C07FreshSourceBootstrapError(
            "C07 fresh-source Alembic graph could not be resolved"
        ) from None

    if (
        bases != (C07_GRAPH_BASE_REVISION,)
        or heads != (C07_TARGET_REVISION,)
        or source is None
        or target is None
        or source.revision != C07_SOURCE_REVISION
        or target.revision != C07_TARGET_REVISION
        or target.down_revision != C07_SOURCE_REVISION
        or set(source.nextrev) != {C07_TARGET_REVISION}
        or not source_chain
        or source_chain[0].revision != C07_SOURCE_REVISION
        or source_chain[-1].revision != C07_GRAPH_BASE_REVISION
        or source_chain[-1].down_revision is not None
        or any(
            revision.dependencies is not None
            or (
                revision.down_revision is not None
                and not isinstance(revision.down_revision, str)
            )
            for revision in source_chain
        )
    ):
        raise C07FreshSourceBootstrapError(
            "C07 fresh-source Alembic graph differs from the frozen release"
        )
    return FreshSourceAlembicPlan(
        config=config, source_revision=C07_SOURCE_REVISION, target_revision=C07_TARGET_REVISION
    )


def _validated_migrator_url(database_url: str) -> URL:
    if not isinstance(database_url, str) or not database_url:
        raise C07FreshSourceBootstrapError("fresh-source database URL must be explicit")
    try:
        parsed = make_url(database_url)
    except (SQLAlchemyError, ValueError):
        raise C07FreshSourceBootstrapError("fresh-source database URL is invalid") from None
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise C07FreshSourceBootstrapError("fresh-source database URL must use PostgreSQL psycopg")
    if (
        parsed.username != MIGRATOR_ROLE
        or parsed.password is not None
        or parsed.database != DATABASE_NAME
        or parsed.host is None
        or parsed.port is None
        or not 1 <= parsed.port <= 65535
        or set(parsed.query) != {"require_auth"}
        or parsed.query.get("require_auth") != "scram-sha-256"
    ):
        raise C07FreshSourceBootstrapError(
            "fresh-source database URL violates the migrator contract"
        )
    try:
        address = ipaddress.ip_address(parsed.host)
    except ValueError:
        raise C07FreshSourceBootstrapError(
            "fresh-source database URL host must be a loopback IP literal"
        ) from None
    if not address.is_loopback:
        raise C07FreshSourceBootstrapError("fresh-source database URL host must be loopback")
    return parsed.set(drivername="postgresql+psycopg")


def _validated_pgpass_path(path: Path) -> Path:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.parent.name != "TicketboxInstallerSecrets"
        or _PGPASS_NAME.fullmatch(path.name) is None
    ):
        raise C07FreshSourceBootstrapError("fresh-source pgpass path is outside the protected layout")
    return path


@contextmanager
def _temporary_pgpass_environment(path: Path) -> Iterator[None]:
    if "PGPASSWORD" in os.environ:
        raise C07FreshSourceBootstrapError("PGPASSWORD is forbidden for fresh-source bootstrap")
    previous = os.environ.get("PGPASSFILE")
    os.environ["PGPASSFILE"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("PGPASSFILE", None)
        else:
            os.environ["PGPASSFILE"] = previous


def _create_fresh_source_engine(database_url: URL) -> Engine:
    return create_engine(
        database_url,
        connect_args={
            "connect_timeout": 10,
            "options": "-c timezone=utc",
        },
        poolclass=NullPool,
        future=True,
    )


def _assert_migrator_authority(connection: Connection) -> None:
    principal = connection.execute(
        text("SELECT session_user, current_user, current_database()")
    ).one()
    if tuple(str(value) for value in principal) != (
        MIGRATOR_ROLE,
        MIGRATOR_ROLE,
        DATABASE_NAME,
    ):
        raise C07FreshSourceBootstrapError(
            "fresh-source connection is not the dedicated migrator"
        )

    connection.execute(text(f'SET LOCAL ROLE "{SCHEMA_OWNER_ROLE}"'))
    effective = connection.execute(
        text("SELECT session_user, current_user")
    ).one()
    if tuple(str(value) for value in effective) != (
        MIGRATOR_ROLE,
        SCHEMA_OWNER_ROLE,
    ):
        raise C07FreshSourceBootstrapError(
            "fresh-source migrator could not assume the schema owner"
        )

    owners = connection.execute(
        text(
            "SELECT pg_get_userbyid(db.datdba), "
            "pg_get_userbyid(ns.nspowner) "
            "FROM pg_database AS db "
            "JOIN pg_namespace AS ns ON ns.nspname = 'public' "
            "WHERE db.datname = current_database()"
        )
    ).one_or_none()
    if owners is None or tuple(str(value) for value in owners) != (
        SCHEMA_OWNER_ROLE,
        SCHEMA_OWNER_ROLE,
    ):
        raise C07FreshSourceBootstrapError(
            "fresh-source database/schema ownership is not exact"
        )


def _public_relations(connection: Connection) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(name), str(kind))
        for name, kind in connection.execute(
            text(
                """
                SELECT rel.relname, rel.relkind
                FROM pg_class AS rel
                JOIN pg_namespace AS ns ON ns.oid = rel.relnamespace
                WHERE ns.nspname = 'public'
                ORDER BY rel.relname, rel.relkind
                """
            )
        )
    )


def _public_non_relation_objects(
    connection: Connection,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(kind), str(name))
        for kind, name in connection.execute(
            text(
                """
                SELECT candidate.kind, candidate.name FROM (
                    SELECT 'routine'::text AS kind,
                        proc.proname || '(' ||
                        pg_get_function_identity_arguments(proc.oid) || ')' AS name
                    FROM pg_proc AS proc
                    JOIN pg_namespace AS ns ON ns.oid = proc.pronamespace
                    WHERE ns.nspname = 'public'
                    UNION ALL
                    SELECT 'type', typ.typname
                    FROM pg_type AS typ
                    JOIN pg_namespace AS ns ON ns.oid = typ.typnamespace
                    WHERE ns.nspname = 'public'
                        AND typ.typrelid = 0 AND typ.typelem = 0
                    UNION ALL
                    SELECT 'extension', ext.extname
                    FROM pg_extension AS ext
                    JOIN pg_namespace AS ns ON ns.oid = ext.extnamespace
                    WHERE ns.nspname = 'public'
                    UNION ALL
                    SELECT 'collation', coll.collname
                    FROM pg_collation AS coll
                    JOIN pg_namespace AS ns ON ns.oid = coll.collnamespace
                    WHERE ns.nspname = 'public'
                    UNION ALL
                    SELECT 'conversion', conv.conname
                    FROM pg_conversion AS conv
                    JOIN pg_namespace AS ns ON ns.oid = conv.connamespace
                    WHERE ns.nspname = 'public'
                ) AS candidate
                ORDER BY candidate.kind, candidate.name
                """
            )
        )
    )


def _assert_empty_version_table(connection: Connection) -> None:
    columns = tuple(
        connection.execute(
            text(
                """
                SELECT attr.attname,
                    format_type(attr.atttypid, attr.atttypmod),
                    attr.attnotnull,
                    pg_get_expr(def.adbin, def.adrelid)
                FROM pg_attribute AS attr
                JOIN pg_class AS rel ON rel.oid = attr.attrelid
                JOIN pg_namespace AS ns ON ns.oid = rel.relnamespace
                LEFT JOIN pg_attrdef AS def
                    ON def.adrelid = attr.attrelid
                    AND def.adnum = attr.attnum
                WHERE ns.nspname = 'public'
                    AND rel.relname = 'alembic_version'
                    AND attr.attnum > 0
                    AND NOT attr.attisdropped
                ORDER BY attr.attnum
                """
            )
        )
    )
    constraints = tuple(
        connection.execute(
            text(
                """
                SELECT con.conname, con.contype,
                    pg_get_constraintdef(con.oid, true)
                FROM pg_constraint AS con
                WHERE con.conrelid =
                    to_regclass('public.alembic_version')
                ORDER BY con.conname
                """
            )
        )
    )
    revisions = tuple(
        connection.scalars(
            text(
                "SELECT version_num FROM public.alembic_version "
                "ORDER BY version_num"
            )
        )
    )
    if (
        columns
        != (("version_num", "character varying(32)", True, None),)
        or constraints
        != (
            (
                "alembic_version_pkc",
                "p",
                "PRIMARY KEY (version_num)",
            ),
        )
        or revisions
    ):
        raise C07FreshSourceBootstrapError(
            "fresh-source Alembic base table is not canonical and empty"
        )


def _assert_fresh_database_at_base(connection: Connection) -> None:
    schemas = tuple(
        str(value)
        for value in connection.scalars(
            text(
                """
                SELECT ns.nspname
                FROM pg_namespace AS ns
                WHERE ns.nspname <> 'information_schema'
                    AND ns.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
                ORDER BY ns.nspname
                """
            )
        )
    )
    if schemas != ("public",):
        raise C07FreshSourceBootstrapError(
            "fresh-source database has an unexpected user schema"
        )
    if _public_non_relation_objects(connection):
        raise C07FreshSourceBootstrapError(
            "fresh-source database has unexpected public objects"
        )

    relations = _public_relations(connection)
    if not relations:
        return
    if relations != _CANONICAL_EMPTY_VERSION_RELATIONS:
        raise C07FreshSourceBootstrapError(
            "fresh-source database has ambiguous public relations"
        )
    _assert_empty_version_table(connection)


def _current_revision(connection: Connection) -> str | None:
    exists = bool(
        connection.scalar(
            text(
                "SELECT to_regclass('public.alembic_version') IS NOT NULL"
            )
        )
    )
    if not exists:
        return None
    revisions = tuple(
        str(value)
        for value in connection.scalars(
            text(
                "SELECT version_num FROM public.alembic_version "
                "ORDER BY version_num"
            )
        )
    )
    if len(revisions) > 1:
        raise C07FreshSourceBootstrapError(
            "fresh-source database has multiple Alembic revisions"
        )
    return None if not revisions else revisions[0]


def _run_fresh_source_with_connection(
    connection: Connection,
    *,
    plan: FreshSourceAlembicPlan,
) -> dict[str, object]:
    """Run the graph on an already-authorized transaction-bound connection."""

    _assert_fresh_database_at_base(connection)
    if _current_revision(connection) is not None:
        raise C07FreshSourceBootstrapError(
            "fresh-source database is not at Alembic base"
        )

    plan.config.attributes["connection"] = connection
    plan.config.attributes[FRESH_SOURCE_BOOTSTRAP_ATTRIBUTE] = True
    command.upgrade(plan.config, plan.source_revision)
    if _current_revision(connection) != plan.source_revision:
        raise C07FreshSourceBootstrapError(
            "fresh-source bootstrap did not reach the exact predecessor"
        )

    result: dict[str, object] = {
        "schema": FRESH_SOURCE_BOOTSTRAP_RESULT_SCHEMA,
        "source_revision": plan.source_revision,
        "target_revision": plan.target_revision,
        "result": "source_committed",
        "alembic_revision": plan.source_revision,
    }
    if tuple(result) != _RESULT_FIELDS:
        raise AssertionError("fresh-source result field order changed")
    return result


def run_fresh_source_bootstrap_action(
    *,
    database_url: str,
    pgpassfile: Path,
    source_revision: str,
    target_revision: str,
) -> dict[str, object]:
    """Bootstrap a proven-empty installed database to the exact C07 source."""

    if (
        source_revision != C07_SOURCE_REVISION
        or target_revision != C07_TARGET_REVISION
    ):
        raise C07FreshSourceBootstrapError(
            "fresh-source CLI revisions differ from the frozen contract"
        )
    parsed_url = _validated_migrator_url(database_url)
    passfile = _validated_pgpass_path(pgpassfile)
    plan = _load_frozen_alembic_plan()

    engine: Engine | None = None
    try:
        with (
            hold_protected_file_for_read(passfile) as protected_pgpass,
            _temporary_pgpass_environment(protected_pgpass),
        ):
            engine = _create_fresh_source_engine(parsed_url)
            with engine.begin() as connection:
                _assert_migrator_authority(connection)
                return _run_fresh_source_with_connection(
                    connection,
                    plan=plan,
                )
    except C07FreshSourceBootstrapError:
        raise
    except (OSError, SQLAlchemyError, ValueError):
        raise C07FreshSourceBootstrapError(
            "fresh-source PostgreSQL bootstrap failed"
        ) from None
    finally:
        if engine is not None:
            engine.dispose()
