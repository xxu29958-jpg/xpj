"""Audit functions that promise atomicity but perform many commits.

The migration cut-over regression came from a docstring that promised a
single transaction while the implementation wrote several independent
transactions. This lane keeps that contract executable: if a function's
docstring mentions atomic / single transaction / one transaction, the function
must not call ``*.commit()`` more than once.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "app", ROOT / "scripts")
PROMISE_MARKERS = (
    "atomic",
    "single transaction",
    "one transaction",
    "same transaction",
)


class CommitCounter(ast.NodeVisitor):
    def __init__(self) -> None:
        self.count = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "commit":
            self.count += 1
        self.generic_visit(node)


def _promises_atomicity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    doc = ast.get_docstring(node) or ""
    lowered = doc.casefold()
    return any(marker in lowered for marker in PROMISE_MARKERS)


def _commit_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    counter = CommitCounter()
    for statement in node.body:
        counter.visit(statement)
    return counter.count


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        if not root.is_dir():
            continue
        files.extend(path for path in root.rglob("*.py") if path.name != Path(__file__).name)
    return sorted(files)


def main() -> int:
    failures: list[str] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{path.relative_to(ROOT)}: syntax error: {exc}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not _promises_atomicity(node):
                continue
            commits = _commit_count(node)
            if commits > 1:
                rel = path.relative_to(ROOT)
                failures.append(f"{rel}:{node.lineno} {node.name} promises atomicity but calls commit {commits} times")

    if failures:
        print("FAIL: atomicity promise does not match transaction boundaries:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("OK: atomicity docstrings do not hide multiple commit calls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
