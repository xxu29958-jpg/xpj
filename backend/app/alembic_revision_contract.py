"""Shared guards for release-frozen Alembic revision chains."""

from __future__ import annotations

from collections.abc import Callable

from alembic.script import ScriptDirectory


def assert_linear_descendant_chain(
    scripts: ScriptDirectory,
    *,
    target_revision: str,
    head_revision: str,
    error_factory: Callable[[str], Exception],
    error_message: str,
) -> None:
    """Require every later packaged revision to be one strict linear child."""

    current = scripts.get_revision(target_revision)
    visited = {target_revision}
    while current is not None and current.revision != head_revision:
        next_revisions = tuple(current.nextrev)
        if len(next_revisions) != 1:
            raise error_factory(error_message)
        successor = scripts.get_revision(next_revisions[0])
        if (
            successor is None
            or successor.revision in visited
            or successor.down_revision != current.revision
            or successor.dependencies is not None
        ):
            raise error_factory(error_message)
        visited.add(successor.revision)
        current = successor
    if current is None or current.revision != head_revision:
        raise error_factory(error_message)


__all__ = ["assert_linear_descendant_chain"]
