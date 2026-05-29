"""Audit release-gate allowlist reasons.

Allowlist entries are an explicit risk ledger, not a place to hide drift. This
lane enforces a minimum contract for every top-level ``ALLOWLIST`` dict in the
audit scripts: string key, specific one-line string reason, no placeholder
language, and no unsupported ownership/single-writer scope claim.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PLACEHOLDERS = ("to" + "do", "tb" + "d", "wi" + "p", "temporary", "misc", "unknown", "later")
PLACEHOLDER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])("
    + "|".join(re.escape(word) for word in PLACEHOLDERS)
    + r")(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
REVIEWABLE_REASON_PATTERN = re.compile(
    r"(?i)\b("
    r"create|owner-only|terminal|idempotent|read-only|preview|append-only|"
    r"upsert|replace-all|health|static|legacy|covered by|loopback|internal|"
    r"single-writer|session refresh|upload|no data surface|versioned row|"
    r"batch|bulk|advisor|session-level|task cancel|rollback|owner-console-only|"
    r"permission-gated|governance|role assignment|manual rate edit|maintenance|"
    r"snapshot|one-shot|server config"
    r")\b"
)

SINGLE_WRITER_ROUTE_ALLOWLIST = frozenset(
    {
        "PUT /api/dashboard/cards",
        "PUT /api/me/ui-preferences",
        "POST /web/dashboard/cards/save",
    }
)


def _reason_uses_placeholder(reason: str) -> bool:
    return PLACEHOLDER_PATTERN.search(reason) is not None


def _top_level_allowlists(tree: ast.Module) -> list[ast.Dict]:
    allowlists: list[ast.Dict] = []
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ALLOWLIST"
                for target in statement.targets
            )
            and isinstance(statement.value, ast.Dict)
        ):
            allowlists.append(statement.value)
            continue
        if (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ALLOWLIST"
                for target in statement.targets
            )
        ):
            continue
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "ALLOWLIST"
            and isinstance(statement.value, ast.Dict)
        ):
            allowlists.append(statement.value)
    return allowlists


def _route_path(key: str) -> str:
    parts = key.split(" ", 1)
    return parts[1] if len(parts) == 2 else ""


def _scope_claim_failure(key: str, reason: str) -> str | None:
    lowered = reason.casefold()
    path = _route_path(key)
    if "owner-console-only" in lowered and not path.startswith("/owner/"):
        return "owner-console-only reason is only valid for /owner routes"
    if "owner-only" in lowered and not (
        path.startswith("/owner/") or path.startswith("/api/admin/")
    ):
        return "owner-only reason is only valid for /owner or /api/admin routes"
    if "single-writer" in lowered and not (
        path.startswith("/owner/") or key in SINGLE_WRITER_ROUTE_ALLOWLIST
    ):
        return "single-writer reason must be owner-scoped or explicitly allowlisted"
    return None


def main() -> int:
    failures: list[str] = []
    scanned_files = 0
    for path in sorted(SCRIPTS.glob("_audit_*.py")):
        if path.name == Path(__file__).name:
            continue
        scanned_files += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for allowlist in _top_level_allowlists(tree):
            for key_node, value_node in zip(allowlist.keys, allowlist.values, strict=False):
                if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                    failures.append(f"{path.name}: ALLOWLIST key must be a string literal")
                    continue
                key = key_node.value
                if not isinstance(value_node, ast.Constant) or not isinstance(value_node.value, str):
                    failures.append(f"{path.name}: {key}: reason must be a string literal")
                    continue
                reason = value_node.value.strip()
                if len(reason) < 12:
                    failures.append(f"{path.name}: {key}: reason is too short")
                if "\n" in reason:
                    failures.append(f"{path.name}: {key}: reason must be one line")
                if _reason_uses_placeholder(reason):
                    failures.append(f"{path.name}: {key}: reason uses placeholder wording")
                if REVIEWABLE_REASON_PATTERN.search(reason) is None:
                    failures.append(f"{path.name}: {key}: reason lacks a reviewed invariant keyword")
                scope_failure = _scope_claim_failure(key, reason)
                if scope_failure is not None:
                    failures.append(f"{path.name}: {key}: {scope_failure}")

    if scanned_files == 0:
        # Fail closed: zero discovered audit scripts means the corpus moved or
        # the script ran from the wrong place — never pass vacuously.
        print(
            "FAIL: audit allowlist lane found no _audit_*.py scripts under "
            f"{SCRIPTS}; discovery is broken, refusing to pass without scanning."
        )
        return 1
    if failures:
        print("FAIL: audit allowlist reasons are not reviewable:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"OK: audit allowlist reasons are concrete, scoped one-line strings "
        f"({scanned_files} script(s) scanned)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
