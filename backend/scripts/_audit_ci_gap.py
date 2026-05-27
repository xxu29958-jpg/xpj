"""Read-only audit: CI invokes every gradle task / pytest lane we expect.

Catches the class of gap that hid ``connectedGrayDebugAndroidTest``
until the v1.0 maturity audit — the task was wired up in the project
but CI never invoked it, so the existing ``Android`` job stayed green
while the only instrumented test we had never actually ran.

The check is intentionally dumb: a hand-maintained whitelist below
must each appear verbatim somewhere under ``.github/workflows/*.yml``
(any workflow — the lane may live in a sibling workflow file such as
``android-connected-test.yml``). Adding a new gradle task / pytest
lane that should be enforced → add it to the whitelist; CI gap is
caught immediately.

Exit code 0 if every entry is referenced. Exit code 1 otherwise, with
the missing entries listed on stdout.
"""

from __future__ import annotations

import pathlib
import sys

# Gradle tasks that CI must invoke. Update when adding a new test /
# lint / build lane that should not silently regress.
REQUIRED_GRADLE_TASKS = [
    ":app:testGrayDebugUnitTest",
    ":app:assembleGrayDebug",
    ":app:assembleInternalDebug",
    ":app:lintGrayDebug",
    ":app:connectedGrayDebugAndroidTest",
]

# Backend invocations expected in CI. Substring match — keep these
# short enough to survive minor flag reorderings, but concrete enough
# that deleting the release audit step fails this lane.
REQUIRED_CI_INVOCATIONS = [
    "scripts\\release_audit.py",
    "pytest --cov=app",
    "pytest -q -m file_backed_only",
]


def _locate_workflow_dir() -> pathlib.Path | None:
    candidates = [
        pathlib.Path("../.github/workflows"),
        pathlib.Path(".github/workflows"),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def main() -> int:
    workflow_dir = _locate_workflow_dir()
    if workflow_dir is None:
        print("CI gap audit: FAIL — .github/workflows/ directory not found")
        return 1

    # Concatenate all workflow files so the check is "gated somewhere
    # in CI?" not "gated in ci.yml?". Catches splits where one
    # workflow runs unit tests and a sibling runs the emulator lane.
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(workflow_dir.glob("*.yml"))
    )

    missing: list[str] = []
    for task in REQUIRED_GRADLE_TASKS:
        if task not in combined:
            missing.append(f"gradle task: {task}")
    for invocation in REQUIRED_CI_INVOCATIONS:
        if invocation not in combined:
            missing.append(f"ci invocation: {invocation}")

    if missing:
        print("=== CI gap audit: FAIL ===")
        for entry in missing:
            print(f"  missing across .github/workflows/*.yml: {entry}")
        return 1

    print(
        f"=== CI gap audit: OK ({len(REQUIRED_GRADLE_TASKS)} gradle tasks + "
        f"{len(REQUIRED_CI_INVOCATIONS)} backend invocations verified across all "
        f".github/workflows/*.yml) ==="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
