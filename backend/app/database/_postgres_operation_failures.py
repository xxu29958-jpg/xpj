"""Preserve PostgreSQL primary and cleanup failures at owner boundaries."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol, cast


class _Disposable(Protocol):
    def dispose(self) -> None: ...


class PostgresOperationFailureError(RuntimeError):
    """A PostgreSQL operation and one or more cleanup actions failed."""

    def __init__(
        self,
        message: str,
        *,
        primary: Exception | None,
        cleanup: tuple[Exception, ...],
    ) -> None:
        if primary is None and not cleanup:
            raise ValueError("PostgreSQL aggregate requires at least one failure")
        self.primary = primary
        self.cleanup = cleanup
        super().__init__(message)


def exit_postgres_owned_context(
    *,
    context: AbstractContextManager[Any],
    primary: BaseException | None,
    cleanup: list[BaseException],
) -> BaseException | None:
    """Exit one owned context without allowing it to replace earlier failure truth."""

    active = cleanup[-1] if cleanup else primary
    try:
        context.__exit__(
            type(active) if active is not None else None,
            active,
            active.__traceback__ if active is not None else None,
        )
    except BaseException as exc:  # noqa: BLE001 - context cleanup is an owned boundary
        if primary is None and not cleanup:
            return exc
        cleanup.append(exc)
    return primary


def close_postgres_owner_resources(
    *,
    contexts: list[AbstractContextManager[Any]],
    engine: _Disposable | None,
    primary: BaseException | None,
    cleanup: list[BaseException],
) -> BaseException | None:
    """Close entered contexts in reverse order, then dispose their engine."""

    for context in reversed(contexts):
        primary = exit_postgres_owned_context(
            context=context,
            primary=primary,
            cleanup=cleanup,
        )
    if engine is not None:
        try:
            engine.dispose()
        except BaseException as exc:  # noqa: BLE001 - engine cleanup is an owned boundary
            if primary is None and not cleanup:
                return exc
            cleanup.append(exc)
    return primary


def raise_postgres_operation_failures(
    *,
    primary: BaseException | None,
    cleanup: list[BaseException],
    message: str,
) -> None:
    """Raise the exact failure, or one aggregate preserving every failure."""

    if primary is None and not cleanup:
        return
    if primary is not None and not cleanup:
        raise primary
    if primary is None and len(cleanup) == 1:
        raise cleanup[0]
    failures = ([primary] if primary is not None else []) + cleanup
    if any(not isinstance(failure, Exception) for failure in failures):
        group = BaseExceptionGroup(message, failures)
        cause = primary if primary is not None else cleanup[0]
        raise group from cause
    aggregate = PostgresOperationFailureError(
        message,
        primary=cast(Exception | None, primary),
        cleanup=tuple(cast(Exception, failure) for failure in cleanup),
    )
    cause = primary if primary is not None else cleanup[0]
    raise aggregate from cause


__all__ = [
    "PostgresOperationFailureError",
    "close_postgres_owner_resources",
    "exit_postgres_owned_context",
    "raise_postgres_operation_failures",
]
