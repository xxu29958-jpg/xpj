"""One authorized, read-only PostgreSQL snapshot for the portable data outlet."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import ExitStack
from itertools import chain

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import FinancialAccount
from app.schemas import GoalResponse
from app.services.envelope_query import redact_envelope_snapshot
from app.services.funds_visibility import account_scope
from app.services.goal_credit_projection import redact_credit_goal_receipt
from app.services.portable_export_access import revalidate_portable_export_context
from app.services.portable_export_archive import PortableArchive, PortableExportCancelledError, create_portable_archive
from app.services.portable_export_queries import portable_original_history_query, portable_projections, portable_queries
from app.tenants import AuthContext


def _raise_if_cancelled(cancel_requested: Callable[[], bool] | None) -> None:
    if cancel_requested is not None and cancel_requested():
        raise PortableExportCancelledError


def _rows(snapshot: Session, query: Select,
          cancel_requested: Callable[[], bool] | None = None, *,
          collection: str | None = None, auth: AuthContext | None = None) -> Iterator[Mapping[str, object]]:
    _raise_if_cancelled(cancel_requested)
    visible = set(snapshot.scalars(select(FinancialAccount.public_id).where(account_scope(auth.ledger_id, auth.account_id)))) \
        if collection == "envelope_revisions" and auth is not None else set()
    with snapshot.execute(query.execution_options(yield_per=250)) as result:
        for row in result.mappings():
            if collection == "envelope_revisions":
                row = {**row, "allocation_snapshot": redact_envelope_snapshot(row["allocation_snapshot"], visible)}
            if (collection == "accepted_operations" and row["resource_type"] == "goal"
                    and isinstance(row["response_body"], dict) and row["response_body"].get("debt_repayment")):
                original = GoalResponse.model_validate(row["response_body"])
                authorized = redact_credit_goal_receipt(snapshot, row["tenant_id"], original)
                if authorized is not original:
                    row = {**row, "response_body": {**row["response_body"],
                        "debt_repayment": authorized.debt_repayment.model_dump(mode="json")},
                        "response_body_redaction_reason": "private_credit_scope"}
            yield row


def _cancel_aware(rows: Iterable[Mapping[str, object]],
                  cancel_requested: Callable[[], bool] | None) -> Iterator[Mapping[str, object]]:
    iterator = iter(rows)
    while True:
        _raise_if_cancelled(cancel_requested)
        try:
            yield next(iterator)
        except StopIteration:
            return


def create_portable_ledger_export(db: Session, *, auth: AuthContext,
                                  cancel_requested: Callable[[], bool] | None = None) -> PortableArchive:
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
            _raise_if_cancelled(cancel_requested)
            with engine.connect().execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True,
            ) as connection, Session(bind=connection, autoflush=False) as snapshot:
                snapshot.execute(select(func.set_config("statement_timeout", "30000ms", True)))
                current = revalidate_portable_export_context(snapshot, auth)
                snapshot_at = snapshot.scalar(select(func.transaction_timestamp()))
                queries = portable_queries(current)
                sections = chain(((name, _rows(snapshot, query, cancel_requested, collection=name, auth=current)) for name, query in queries),
                                 ((name, _cancel_aware(rows, cancel_requested))
                                  for name, rows in portable_projections(snapshot, current)))
                archive = create_portable_archive(
                    ledger_id=current.ledger_id, snapshot_at=snapshot_at,
                    account_public_id=current.account_public_id,
                    sections=sections,
                    originals=_rows(snapshot, dict(queries)["expenses"], cancel_requested),
                    historical_originals=_rows(
                        snapshot, portable_original_history_query(current), cancel_requested),
                    cancel_requested=cancel_requested,
                )
                abort.callback(archive.close)
            with Session(bind=engine, autoflush=False) as current_read:
                _raise_if_cancelled(cancel_requested)
                revalidate_portable_export_context(current_read, auth)
            abort.pop_all()
            return archive
    except (SQLAlchemyError, OSError) as exc:
        raise AppError("portable_export_unavailable", status_code=503) from exc
