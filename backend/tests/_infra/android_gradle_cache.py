from __future__ import annotations

from typing import Any

_SETUP_GRADLE_ACTION = (
    "gradle/actions/setup-gradle@3f131e8634966bd73d06cc69884922b02e6faf92"
)


def assert_gradle_cache_authority(
    job: dict[str, Any],
    *,
    java_version: str,
    cache_read_only: str | bool,
) -> None:
    steps = {step["name"]: step for step in job["steps"]}
    setup_gradle_steps = [
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("gradle/actions/setup-gradle@")
    ]
    assert len(setup_gradle_steps) == 1
    java = steps["Set up Java"]
    assert java["with"] == {
        "distribution": "temurin",
        "java-version": java_version,
    }
    gradle = steps["Set up Gradle"]
    assert gradle["uses"] == _SETUP_GRADLE_ACTION
    assert gradle["with"] == {
        "cache-provider": "basic",
        "cache-read-only": cache_read_only,
    }
    step_names = [step["name"] for step in job["steps"]]
    assert step_names.index("Set up Java") < step_names.index("Set up Gradle")


def assert_github_gradle_cache_topology(
    workflows: dict[str, dict[str, Any]],
) -> None:
    writers = []
    for workflow_name, workflow in workflows.items():
        for job_name, job in workflow.get("jobs", {}).items():
            for step in job.get("steps", []):
                uses = str(step.get("uses", ""))
                if not uses.startswith("gradle/actions/setup-gradle@"):
                    continue
                assert uses == _SETUP_GRADLE_ACTION
                expected_read_only: str | bool = True
                if workflow_name == "ci.yml" and job_name == "android":
                    expected_read_only = "${{ github.ref != 'refs/heads/main' }}"
                    writers.append((workflow_name, job_name))
                assert step["with"] == {
                    "cache-provider": "basic",
                    "cache-read-only": expected_read_only,
                }
    assert writers == [("ci.yml", "android")]
