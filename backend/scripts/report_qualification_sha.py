"""Verify and report the immutable checkout used by a CI qualification job."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


def _validated_sha(value: str, label: str) -> str:
    if _COMMIT_SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase 40-character commit id")
    return value


def _checkout_parent_shas() -> tuple[str, ...]:
    """Read raw commit headers so shallow checkout boundaries cannot hide parents."""
    parent_result = subprocess.run(
        ["git", "cat-file", "-p", "HEAD^{commit}"],
        cwd=_REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    headers, separator, _message = parent_result.stdout.partition("\n\n")
    if not separator:
        raise RuntimeError("qualification checkout commit object is malformed")
    parents = tuple(
        _validated_sha(line.removeprefix("parent "), "qualification parent SHA")
        for line in headers.splitlines()
        if line.startswith("parent ")
    )
    return parents


def report_qualification_sha(
    expected_sha: str,
    source_sha: str,
    output_path: Path,
) -> tuple[str, str]:
    expected_sha = _validated_sha(expected_sha, "expected qualification SHA")
    source_sha = _validated_sha(source_sha, "source qualification SHA")
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=_REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    actual_sha = completed.stdout.strip()
    if actual_sha != expected_sha:
        raise RuntimeError(
            f"qualification checkout mismatch: expected={expected_sha} actual={actual_sha}"
        )
    if source_sha != actual_sha and source_sha not in _checkout_parent_shas():
        raise RuntimeError(
            "qualification source is not a direct parent of the checkout: "
            f"source={source_sha} checkout={actual_sha}"
        )
    with output_path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(f"sha={actual_sha}\n")
        output.write(f"source_sha={source_sha}\n")
    print(f"Qualification checkout SHA: {actual_sha}; source SHA: {source_sha}")
    return actual_sha, source_sha


def resolve_audit_base(environment: Mapping[str, str]) -> str:
    try:
        from scripts.adr_contract_git import select_ratchet_base
    except ModuleNotFoundError:
        from adr_contract_git import select_ratchet_base

    selected, error = select_ratchet_base(_REPOSITORY_ROOT, dict(environment))
    if selected is None:
        raise RuntimeError(error or "audit ratchet base selection failed")
    return _validated_sha(selected.commit, "audit base SHA")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit-base", action="store_true")
    arguments = parser.parse_args()
    audit_base = resolve_audit_base(os.environ) if arguments.audit_base else None
    report_qualification_sha(arguments.expected, arguments.source, arguments.output)
    if audit_base is not None:
        with arguments.output.open("a", encoding="utf-8", newline="\n") as output:
            output.write(f"audit_base_sha={audit_base}\n")
        print(f"Audit ratchet base SHA: {audit_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
