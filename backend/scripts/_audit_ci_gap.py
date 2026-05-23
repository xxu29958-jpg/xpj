"""Read-only audit: CI invokes every gradle task / pytest lane we expect.

Catches the class of gap that hid ``connectedGrayDebugAndroidTest``
until the v1.0 maturity audit — the task was wired up in the project
but CI never invoked it, so the existing ``Android`` job stayed green
while the only instrumented test we had never actually ran.

The check is intentionally dumb: a hand-maintained whitelist below
must each appear verbatim somewhere in ``.github/workflows/ci.yml``.
Adding a new gradle task / pytest lane that should be enforced →
add it to the whitelist; CI gap is caught immediately.

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

# Backend pytest invocations expected in CI. Substring match — keep
# these short enough to survive minor flag reorderings.
REQUIRED_PYTEST_LANES = [
    "pytest --cov=app",
    "pytest -q -m file_backed_only",
]


def _locate_workflow() -> pathlib.Path | None:
    candidates = [
        pathlib.Path("../.github/workflows/ci.yml"),
        pathlib.Path(".github/workflows/ci.yml"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def main() -> int:
    workflow = _locate_workflow()
    if workflow is None:
        print("CI gap audit: FAIL — .github/workflows/ci.yml not found")
        return 1

    text = workflow.read_text(encoding="utf-8")
    missing: list[str] = []
    for task in REQUIRED_GRADLE_TASKS:
        if task not in text:
            missing.append(f"gradle task: {task}")
    for lane in REQUIRED_PYTEST_LANES:
        if lane not in text:
            missing.append(f"pytest lane: {lane}")

    if missing:
        print("=== CI gap audit: FAIL ===")
        for entry in missing:
            print(f"  missing in ci.yml: {entry}")
        return 1

    print(
        f"=== CI gap audit: OK ({len(REQUIRED_GRADLE_TASKS)} gradle tasks + "
        f"{len(REQUIRED_PYTEST_LANES)} pytest lanes verified) ==="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
