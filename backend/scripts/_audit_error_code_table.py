"""Read-only audit: a message-less ``AppError(code, ...)`` code must be in
``ERROR_MESSAGES``.

``AppError`` resolves its user-facing message as
``message or ERROR_MESSAGES.get(error, ERROR_MESSAGES["server_error"])``. So a
call that passes ONLY a code (no explicit message positional) and whose code is
absent from the table silently degrades to "服务器开小差了" — a 404/409 rendered
as a generic 500-style line. The 2026-06-10 audit (#17) found ``not_found`` /
``task_not_found`` doing exactly this; this lane pins the rule so the class can't
silently return.

What counts as "has an explicit message": a SECOND positional arg to
``AppError`` (``AppError("code", "中文")``). ``status_code=`` / ``details=`` are
keyword-only and do NOT supply a message, so ``AppError("code", status_code=404)``
still depends on the table and is checked. Calls whose first arg is not a string
literal (dynamic code) are skipped — they can't be statically resolved.

Run from ``backend/``::

    .venv/Scripts/python.exe scripts/_audit_error_code_table.py

Exit 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import ast
import pathlib
import sys

APP_DIR = pathlib.Path("app")
ERRORS_FILE = APP_DIR / "errors.py"


def _error_message_keys() -> set[str]:
    """Parse the ``ERROR_MESSAGES`` dict literal keys from errors.py (AST, so a
    stray same-named string elsewhere can't pollute the set)."""
    tree = ast.parse(ERRORS_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        is_table_assign = isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ERROR_MESSAGES" for t in node.targets
        )
        if is_table_assign and isinstance(node.value, ast.Dict):
            return {
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    raise SystemExit("ERROR_MESSAGES dict literal not found in app/errors.py")


def _messageless_apperror_codes(tree: ast.AST) -> list[tuple[int, str]]:
    """(lineno, code) for every ``AppError`` call that passes only a code
    (no second positional message arg) and a string-literal code."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "AppError":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue  # dynamic code — not statically resolvable
        has_message = len(node.args) >= 2  # second positional is the message
        if not has_message:
            out.append((node.lineno, first.value))
    return out


def main() -> int:
    keys = _error_message_keys()
    failures: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, code in _messageless_apperror_codes(tree):
            if code not in keys:
                failures.append(
                    f"{path.as_posix()}:{lineno} AppError(\"{code}\") has no explicit "
                    f"message and \"{code}\" is not in ERROR_MESSAGES -> degrades to server_error"
                )

    print("Message-less AppError codes are all in ERROR_MESSAGES:")
    if failures:
        for line in failures:
            print(f"  FAIL  {line}")
    else:
        print(f"  OK  ({len(keys)} table entries; every message-less AppError code covered)")
    ok = not failures
    print(f"\n{'PASS' if ok else 'FAIL'}  error-code-table")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
