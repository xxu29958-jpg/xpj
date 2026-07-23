"""Resolve the heavy CI jobs required by a pull request.

This is deliberately a path classifier, not a test-impact engine.  Unknown
paths and CI-policy changes fall back to the complete job set.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

if __package__:
    from .ci_gap_trigger_scope import CI_HEAVY_SCOPES, all_ci_scopes, classify_ci_paths
    from .postgres_release_policy import POSTGRES_RELEASE_POLICY
else:
    from ci_gap_trigger_scope import CI_HEAVY_SCOPES, all_ci_scopes, classify_ci_paths
    from postgres_release_policy import POSTGRES_RELEASE_POLICY


def changed_paths(base: str, head: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", "-z", f"{base}...{head}"],
        check=True,
        capture_output=True,
    )
    return [
        entry.decode("utf-8", errors="surrogateescape")
        for entry in completed.stdout.split(b"\0")
        if entry
    ]


def write_outputs(path: Path, scopes: dict[str, bool]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for scope in CI_HEAVY_SCOPES:
            output.write(f"{scope}={'true' if scopes[scope] else 'false'}\n")
        output.write(f"postgres_matrix={POSTGRES_RELEASE_POLICY.matrix_json()}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    scopes = all_ci_scopes()
    if args.event in {"pull_request", "push"} and args.base and args.head:
        try:
            paths = changed_paths(args.base, args.head)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"CI scope diff failed; running all heavy jobs: {exc}")
        else:
            scopes = classify_ci_paths(paths)
            print("Changed paths:")
            for path in paths:
                print(f"  {path}")

    print(
        "CI heavy-job scope: "
        + ", ".join(f"{key}={value}" for key, value in scopes.items())
    )
    write_outputs(args.output, scopes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
