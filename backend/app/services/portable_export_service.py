"""One authorized, read-only PostgreSQL snapshot for the portable data outlet."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack
from itertools import chain

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.services.portable_export_archive import PortableArchive, create_portable_archive
from app.services.portable_export_queries import portable_original_history_query, portable_projections, portable_queries
from app.services.session_credential_lock import revalidate_session_context
from app.tenants import AuthContext


def _rows(snapshot: Session, query: Select) -> Iterator[Mapping[str, object]]:
    with snapshot.execute(query.execution_options(yield_per=250)) as result:
        yield from result.mappings()


def create_portable_ledger_export(db: Session, *, auth: AuthContext) -> PortableArchive:
    """Return a request-owned package; never flush/commit/rollback the caller.

    The existing authentication entry already established this app identity;
    download routes release their completed request reads before calling here.
    A separate connection makes the data snapshot independent of its activity
    transaction, and a final fresh check discards a package on lost authority.
    File evidence is observed through the existing stable original reader;
    its per-reference outcome does not pretend the filesystem is an MVCC store.
    """
    if auth.scope != "app":
        raise AppError("invalid_token", status_code=401)
    engine = db.get_bind().engine
    try:
        with ExitStack() as abort:
            with engine.connect().execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True,
            ) as connection, Session(bind=connection, autoflush=False) as snapshot:
                snapshot.execute(select(func.set_config("statement_timeout", "30000ms", True)))
                current = revalidate_session_context(snapshot, auth)
                snapshot_at = snapshot.scalar(select(func.transaction_timestamp()))
                queries = portable_queries(current)
                archive = create_portable_archive(
                    ledger_id=current.ledger_id, snapshot_at=snapshot_at,
                    account_public_id=current.account_public_id,
                    sections=chain(((name, _rows(snapshot, query)) for name, query in queries),
                        portable_projections(snapshot, current)),
                    originals=_rows(snapshot, dict(queries)["expenses"]),
                    historical_originals=_rows(snapshot, portable_original_history_query(current)),
                )
                abort.callback(archive.close)
            with Session(bind=engine, autoflush=False) as current_read:
                revalidate_session_context(current_read, auth)
            abort.pop_all()
            return archive
    except (SQLAlchemyError, OSError) as exc:
        raise AppError("portable_export_unavailable", status_code=503) from exc
