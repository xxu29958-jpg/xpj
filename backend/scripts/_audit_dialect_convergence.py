"""Read-only audit: SQLite/PostgreSQL dialect convergence (ADR-0041 phase-1).

The repo runs SQLite in dev and is migrating to PostgreSQL (ADR-0041). During
the dual-dialect window every schema definition and every raw SQL string must
be valid on **both** engines, or the Postgres path breaks in ways the SQLite
test suite can't see. This lane statically guards the regression classes that
already bit us — including ones the Postgres smoke lane can't reach because it
doesn't exercise every code path (e.g. the cut-over singleton-task guard).

Three checks:

- **Partial-index where parity** — a partial-UNIQUE ``Index(... unique=True,
  sqlite_where=...)`` that omits ``postgresql_where`` silently degrades to a
  *whole-table* UNIQUE on Postgres (e.g. ``uq_auth_tokens_active_principal``
  would reject re-issuing a token because a historical revoked row still
  occupies the tuple). The two ``*_where`` clauses must be present together.

- **SQLite-only DML grammar** — ``INSERT OR IGNORE`` / ``INSERT OR REPLACE`` is
  SQLite-only; PostgreSQL rejects it outright. It has a portable replacement
  (check-then-insert), so any occurrence in an ``app/`` or ``migrations/`` SQL
  *string literal* fails — guarded or not.

- **Unguarded SQLite-only SQL on a shared path** — ``BEGIN IMMEDIATE`` and the
  SQLite date functions (``datetime()`` / ``strftime()`` / ``julianday()``)
  have no portable form, so on any path that can run under PostgreSQL they MUST
  sit behind an ``if <bind>.dialect.name == "sqlite"`` guard. This is the class
  that crashed the Alembic replay (``20260528_0001`` ``datetime('now', ...)``)
  and the one the smoke missed (``background_task_service`` ``BEGIN IMMEDIATE``
  on the cut-over backup path). The check walks the AST and flags any such
  string literal that is not inside a sqlite-dialect ``if`` block.

  Dedicated SQLite-only modules (``SQLITE_ONLY_MODULES``) are exempt: their
  entry points early-return on a non-sqlite dialect (``migrate_sqlite_schema``,
  ``validate_sqlite_data_integrity``, the pre-v0.3 file backup), a function-
  level guard the block-level walk can't see.

Run from ``backend/``::

    .venv/Scripts/python.exe scripts/_audit_dialect_convergence.py

Exit 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import ast
import pathlib
import sys

MODELS_DIR = pathlib.Path("app/models")
APP_DIR = pathlib.Path("app")
MIGRATIONS_DIR = pathlib.Path("migrations/versions")

# SQLite-only DML grammar PostgreSQL rejects; portable replacement exists, so
# banned everywhere (guarded or not). Lower-cased for comparison.
SQLITE_ONLY_DML = ("insert or ignore", "insert or replace")

# SQLite-only date functions with no portable form. Matched CASE-SENSITIVELY
# (lower-case, the SQL convention) so the CamelCase SQLAlchemy ``DateTime(``
# type written in prose/docstrings is not mistaken for a SQL ``datetime()``
# call. Only flagged inside strings that also read as SQL.
SQLITE_ONLY_DATE_FUNCS = ("datetime(", "strftime(", "julianday(")
# Matched case-insensitively; the code writes it upper-case.
SQLITE_ONLY_TXN = "begin immediate"
_SQL_VERBS = ("select ", "insert ", "update ", "delete ", " set ", " where ", " from ", "values")

# Dedicated SQLite-only modules: their entry point early-returns on a non-sqlite
# dialect (a function-level guard the block-level walk can't see), so SQLite-only
# SQL is correct in them.
SQLITE_ONLY_MODULES = (
    "app/database/_migrations",
    "app/database/_validate",
    "app/database/_backup.py",
    "app/services/sqlite_backup_validation_service.py",
)


def _iter_py(base: pathlib.Path):
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _iter_py_trees(*bases: pathlib.Path):
    for base in bases:
        if not base.exists():
            continue
        for path in _iter_py(base):
            yield path, ast.parse(path.read_text(encoding="utf-8"))


def _is_sqlite_only_module(path: pathlib.Path) -> bool:
    posix = path.as_posix()
    return any(prefix in posix for prefix in SQLITE_ONLY_MODULES)


def _looks_like_sql(text: str) -> bool:
    low = text.lower()
    return any(verb in low for verb in _SQL_VERBS)


def _index_name(call: ast.Call) -> str:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return "<unnamed Index>"


def _check_partial_index_parity() -> list[str]:
    """Every Index with one ``*_where`` clause must declare both dialects'."""
    failures: list[str] = []
    for path in _iter_py(MODELS_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "Index":
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            has_sqlite = "sqlite_where" in kwargs
            has_postgres = "postgresql_where" in kwargs
            if has_sqlite != has_postgres:
                present = "sqlite_where" if has_sqlite else "postgresql_where"
                missing = "postgresql_where" if has_sqlite else "sqlite_where"
                failures.append(
                    f"{path.as_posix()}:{node.lineno} Index({_index_name(node)!r}) "
                    f"declares {present} but not {missing} — partial index would "
                    f"behave differently across dialects"
                )
    return failures


def _check_no_sqlite_only_dml() -> list[str]:
    """No ``INSERT OR IGNORE`` / ``INSERT OR REPLACE`` in app/migration SQL strings."""
    failures: list[str] = []
    for path, tree in _iter_py_trees(APP_DIR, MIGRATIONS_DIR):
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            lowered = node.value.lower()
            failures.extend(
                f"{path.as_posix()}:{node.lineno} SQL string contains SQLite-only "
                f"'{token.upper()}' — PostgreSQL rejects it; use a portable "
                f"check-then-insert"
                for token in SQLITE_ONLY_DML
                if token in lowered
            )
    return failures


def _sqlite_guarded_string_ids(tree: ast.AST) -> set[int]:
    """ids of str-Constant nodes lexically inside an ``if ...sqlite...:`` body.

    The ``orelse`` of a sqlite ``if`` is the *non*-sqlite branch, so it does
    NOT inherit the guard. Any outer guard is still carried in.
    """
    guarded: set[int] = set()

    def visit(node: ast.AST, in_guard: bool) -> None:
        if isinstance(node, ast.If):
            is_sqlite_guard = "sqlite" in ast.unparse(node.test).lower()
            visit(node.test, in_guard)
            for child in node.body:
                visit(child, in_guard or is_sqlite_guard)
            for child in node.orelse:
                visit(child, in_guard)
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and in_guard:
            guarded.add(id(node))
        for child in ast.iter_child_nodes(node):
            visit(child, in_guard)

    visit(tree, False)
    return guarded


def _unguarded_hits(path: pathlib.Path, node: ast.AST, guarded: set[int]) -> list[str]:
    """SQLite-only tokens in one string node that are not behind a sqlite guard."""
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return []
    if id(node) in guarded:
        return []
    raw = node.value
    tokens: list[str] = []
    if SQLITE_ONLY_TXN in raw.lower():
        tokens.append("BEGIN IMMEDIATE")
    if _looks_like_sql(raw):
        tokens.extend(fn for fn in SQLITE_ONLY_DATE_FUNCS if fn in raw)
    guard_hint = 'outside an `if ...dialect... == "sqlite"` guard'
    return [
        f"{path.as_posix()}:{node.lineno} SQL string uses SQLite-only '{token}' "
        f"{guard_hint} — PostgreSQL rejects it on the shared path"
        for token in tokens
    ]


def _check_unguarded_sqlite_only_sql() -> list[str]:
    """SQLite-only SQL on a shared path must sit behind a sqlite-dialect guard."""
    failures: list[str] = []
    for path, tree in _iter_py_trees(APP_DIR, MIGRATIONS_DIR):
        if _is_sqlite_only_module(path):
            continue
        guarded = _sqlite_guarded_string_ids(tree)
        for node in ast.walk(tree):
            failures.extend(_unguarded_hits(path, node, guarded))
    return failures


def _report(title: str, failures: list[str], ok_message: str) -> None:
    print(f"{title}:")
    if failures:
        for line in failures:
            print(f"  FAIL  {line}")
    else:
        print(f"  OK  {ok_message}")


def main() -> int:
    parity = _check_partial_index_parity()
    dml = _check_no_sqlite_only_dml()
    unguarded = _check_unguarded_sqlite_only_sql()

    _report(
        "Partial-index dialect where-parity",
        parity,
        "every partial Index declares both sqlite_where and postgresql_where",
    )
    print()
    _report(
        "SQLite-only DML grammar in app/ + migrations/ SQL strings",
        dml,
        "no INSERT OR IGNORE / INSERT OR REPLACE",
    )
    print()
    _report(
        "Unguarded SQLite-only SQL on shared paths",
        unguarded,
        "BEGIN IMMEDIATE / datetime() / strftime() / julianday() are all sqlite-guarded",
    )

    ok = not parity and not dml and not unguarded
    print(f"\n{'PASS' if ok else 'FAIL'}  dialect-convergence")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
