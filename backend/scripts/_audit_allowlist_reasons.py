"""Audit release-gate allowlist reasons.

Allowlist entries are an explicit risk ledger, not a place to hide drift. This
lane enforces a minimum contract for every top-level ``ALLOWLIST`` dict in the
audit scripts: string key, specific one-line string reason, and no placeholder
language.
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


def _reason_uses_placeholder(reason: str) -> bool:
    return PLACEHOLDER_PATTERN.search(reason) is not None


def _top_level_allowlists(tree: ast.Module) -> list[ast.Dict]:
    allowlists: list[ast.Dict] = []
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "ALLOWLIST" for target in statement.targets):
            continue
        if isinstance(statement.value, ast.Dict):
            allowlists.append(statement.value)
    return allowlists


def main() -> int:
    failures: list[str] = []
    for path in sorted(SCRIPTS.glob("_audit_*.py")):
        if path.name == Path(__file__).name:
            continue
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

    if failures:
        print("FAIL: audit allowlist reasons are not reviewable:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("OK: audit allowlist reasons are concrete one-line strings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
