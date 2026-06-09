"""Read-only audit: partial-UNIQUE indexes declare ``postgresql_where``.

PostgreSQL-only (debt #4). A partial UNIQUE ``Index(..., unique=True,
sqlite_where=...)`` that omits ``postgresql_where`` silently degrades to a
*whole-table* UNIQUE on PostgreSQL — e.g. ``uq_auth_tokens_active_principal``
would reject re-issuing a token because a historical revoked row still occupies
the tuple. This is the one forward-looking guard kept from the retired
``_audit_dialect_convergence`` lane (its SQLite-grammar / ``BEGIN IMMEDIATE``
checks became moot once SQLite was dropped).

The retired dual-dialect ``sqlite_where=`` kwargs have now been removed from the
models: every partial index declares ``postgresql_where`` alone, the correct
PG-only form. This check stays as a forward-looking guard — a new index that
re-introduces ``sqlite_where`` without ``postgresql_where`` (copied from old git
history or SQLAlchemy docs) would silently degrade to a whole-table UNIQUE, and
this catches it.

Run from ``backend/``::

    .venv/Scripts/python.exe scripts/_audit_partial_index_pg_where.py

Exit 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import ast
import pathlib
import sys

MODELS_DIR = pathlib.Path("app/models")


def _iter_py(base: pathlib.Path):
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _index_name(call: ast.Call) -> str:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return "<unnamed Index>"


def _check_partial_index_pg_where() -> list[str]:
    """A partial index that carries a ``sqlite_where`` must also carry
    ``postgresql_where`` — otherwise it is a whole-table UNIQUE on PostgreSQL."""
    failures: list[str] = []
    for path in _iter_py(MODELS_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "Index":
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            if "sqlite_where" in kwargs and "postgresql_where" not in kwargs:
                failures.append(
                    f"{path.as_posix()}:{node.lineno} Index({_index_name(node)!r}) "
                    f"declares sqlite_where but not postgresql_where — the partial "
                    f"clause would not apply on PostgreSQL (whole-table index)"
                )
    return failures


def main() -> int:
    failures = _check_partial_index_pg_where()
    print("Partial-index PostgreSQL where-clause presence:")
    if failures:
        for line in failures:
            print(f"  FAIL  {line}")
    else:
        print("  OK  every partial Index with a where-clause declares postgresql_where")
    ok = not failures
    print(f"\n{'PASS' if ok else 'FAIL'}  partial-index-pg-where")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
