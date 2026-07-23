"""Verify and report the immutable checkout used by a CI qualification job."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


def _validated_sha(value: str, label: str) -> str:
    if _COMMIT_SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase 40-character commit id")
    return value


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
    if source_sha != actual_sha:
        parent_result = subprocess.run(
            ["git", "show", "-s", "--format=%P", "HEAD"],
            cwd=_REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if source_sha not in parent_result.stdout.strip().split():
            raise RuntimeError(
                "qualification source is not a direct parent of the checkout: "
                f"source={source_sha} checkout={actual_sha}"
            )
    with output_path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(f"sha={actual_sha}\n")
        output.write(f"source_sha={source_sha}\n")
    print(f"Qualification checkout SHA: {actual_sha}; source SHA: {source_sha}")
    return actual_sha, source_sha


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    report_qualification_sha(arguments.expected, arguments.source, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
