"""Prove the fail-closed heavy-job scope wiring in GitHub CI."""

from __future__ import annotations

import pathlib
import re

from ci_gap_trigger_scope import CI_HEAVY_SCOPES
from ci_gap_workflow_conditions import allows_failure

HEAVY_JOB_SCOPES = frozenset(CI_HEAVY_SCOPES)
_SCOPE_OUTPUTS = {
    scope: f"${{{{ steps.scope.outputs.{scope} }}}}" for scope in HEAVY_JOB_SCOPES
}
_CHECKOUT_ACTION = re.compile(r"^actions/checkout@[0-9a-f]{40}$")
_SETUP_PYTHON_ACTION = re.compile(r"^actions/setup-python@[0-9a-f]{40}$")
_FAIL_CLOSED_CONDITION = re.compile(
    r"always\(\)\s*&&\s*!cancelled\(\)\s*&&\s*\("
    r"needs\.scope\.result\s*!=\s*(['\"])success\1\s*\|\|\s*"
    r"needs\.scope\.outputs\.([a-z_]+)\s*!=\s*(['\"])false\3\s*\)"
)
_SCOPE_COMMAND = (
    'python -E -S backend/scripts/ci_scope.py --event "${{ github.event_name }}" '
    '--base "${{ github.event.pull_request.base.sha || \'\' }}" '
    '--head "${{ github.event.pull_request.head.sha || github.sha }}" '
    '--output "$GITHUB_OUTPUT"'
)
_REQUIRED_GATE_JOB = "backend"
_REQUIRED_GATE_NEEDS = ("scope", "backend_contracts", "windows_packaging")
_REQUIRED_GATE_ENV = {
    "SCOPE_RESULT": "${{ needs.scope.result }}",
    "BACKEND_CONTRACTS_RESULT": "${{ needs.backend_contracts.result }}",
    "WINDOWS_PACKAGING_RESULT": "${{ needs.windows_packaging.result }}",
}
_REQUIRED_GATE_SCRIPT = " ".join(
    [
        'if [ "$SCOPE_RESULT" != "success" ]; then',
        'echo "::error::CI scope resolution did not succeed: $SCOPE_RESULT"',
        "exit 1",
        "fi",
        'if [ "$BACKEND_CONTRACTS_RESULT" != "success" ]; then',
        'echo "::error::Backend contracts did not succeed: '
        '$BACKEND_CONTRACTS_RESULT"',
        "exit 1",
        "fi",
        'case "$WINDOWS_PACKAGING_RESULT" in',
        "success|skipped) ;;",
        "*)",
        'echo "::error::Windows release packaging did not succeed: '
        '$WINDOWS_PACKAGING_RESULT"',
        "exit 1",
        ";;",
        "esac",
        'echo "Required Backend CI results are valid."',
    ]
)


def job_needs(raw_job: dict[object, object]) -> tuple[str, ...] | None:
    value = raw_job.get("needs")
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else None
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return tuple(value)
    return None


def _expression_text(value: object) -> str:
    expression = str(value).strip()
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2].strip()
    return re.sub(r"\s+", " ", expression)


def _bash_script_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    commands: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            stripped = stripped[:-1].rstrip()
        commands.append(stripped)
    return " ".join(" ".join(commands).split())


def _workflow_execution_shape_is_plain(workflow: dict[object, object]) -> bool:
    return workflow.get("env") is None and workflow.get("defaults") is None


def _job_execution_shape_is_plain(raw_job: dict[object, object]) -> bool:
    return all(
        raw_job.get(field) is None
        for field in ("env", "defaults", "container", "services", "strategy")
    )


def _step_execution_shape_is_plain(
    raw_step: dict[object, object],
    *,
    allow_env: bool = False,
) -> bool:
    return (
        (allow_env or raw_step.get("env") is None)
        and raw_step.get("working-directory") is None
        and raw_step.get("timeout-minutes") is None
    )


def _scope_job_is_valid(
    path: pathlib.Path,
    workflow: dict[object, object],
    jobs: dict[object, object],
) -> bool:
    if ".github" not in path.parts or path.name != "ci.yml":
        return False
    raw_job = jobs.get("scope")
    if (
        not isinstance(raw_job, dict)
        or not _workflow_execution_shape_is_plain(workflow)
        or not _job_execution_shape_is_plain(raw_job)
        or job_needs(raw_job) != ()
        or raw_job.get("if") not in {None, True}
        or allows_failure(raw_job.get("continue-on-error"))
        or raw_job.get("name") != "CI scope"
        or raw_job.get("runs-on") != "ubuntu-latest"
        or raw_job.get("timeout-minutes") != 5
        or raw_job.get("outputs") != _SCOPE_OUTPUTS
    ):
        return False
    steps = raw_job.get("steps")
    if not isinstance(steps, list) or len(steps) != 3:
        return False
    checkout, setup_python, resolver = steps
    checkout_is_complete = (
        isinstance(checkout, dict)
        and _CHECKOUT_ACTION.fullmatch(str(checkout.get("uses", ""))) is not None
        and checkout.get("with") == {"fetch-depth": 0}
        and checkout.get("if") in {None, True}
        and not allows_failure(checkout.get("continue-on-error"))
        and _step_execution_shape_is_plain(checkout)
    )
    setup_is_complete = (
        isinstance(setup_python, dict)
        and _SETUP_PYTHON_ACTION.fullmatch(str(setup_python.get("uses", ""))) is not None
        and setup_python.get("with") == {"python-version": "3.11"}
        and setup_python.get("if") in {None, True}
        and not allows_failure(setup_python.get("continue-on-error"))
        and _step_execution_shape_is_plain(setup_python)
    )
    resolver_is_complete = (
        isinstance(resolver, dict)
        and resolver.get("id") == "scope"
        and resolver.get("shell") == "bash"
        and resolver.get("if") in {None, True}
        and not allows_failure(resolver.get("continue-on-error"))
        and _step_execution_shape_is_plain(resolver)
        and _bash_script_text(resolver.get("run")) == _SCOPE_COMMAND
    )
    return checkout_is_complete and setup_is_complete and resolver_is_complete


def _scoped_job_name(raw_job: dict[object, object]) -> str | None:
    if job_needs(raw_job) != ("scope",) or allows_failure(
        raw_job.get("continue-on-error")
    ):
        return None
    match = _FAIL_CLOSED_CONDITION.fullmatch(_expression_text(raw_job.get("if")))
    if match is None or match.group(2) not in HEAVY_JOB_SCOPES:
        return None
    return match.group(2)


def _required_gate_is_valid(
    workflow: dict[object, object],
    jobs: dict[object, object],
) -> bool:
    raw_job = jobs.get(_REQUIRED_GATE_JOB)
    if (
        not isinstance(raw_job, dict)
        or not _workflow_execution_shape_is_plain(workflow)
        or not _job_execution_shape_is_plain(raw_job)
        or raw_job.get("name") != "Backend"
        or job_needs(raw_job) != _REQUIRED_GATE_NEEDS
        or _expression_text(raw_job.get("if")) != "always()"
        or allows_failure(raw_job.get("continue-on-error"))
        or raw_job.get("runs-on") != "ubuntu-latest"
        or raw_job.get("timeout-minutes") != 5
        or any(
            not isinstance(jobs.get(dependency), dict)
            for dependency in _REQUIRED_GATE_NEEDS
        )
    ):
        return False
    steps = raw_job.get("steps")
    if not isinstance(steps, list) or len(steps) != 1:
        return False
    step = steps[0]
    return (
        isinstance(step, dict)
        and step.get("name") == "Enforce required CI results"
        and step.get("shell") == "bash"
        and step.get("if") in {None, True}
        and not allows_failure(step.get("continue-on-error"))
        and step.get("env") == _REQUIRED_GATE_ENV
        and _step_execution_shape_is_plain(step, allow_env=True)
        and _bash_script_text(step.get("run")) == _REQUIRED_GATE_SCRIPT
    )


def scoped_job_protection_scope(
    path: pathlib.Path,
    workflow: dict[object, object],
    raw_job: dict[object, object],
    jobs: dict[object, object],
) -> str | None:
    if (
        not _scope_job_is_valid(path, workflow, jobs)
        or not _required_gate_is_valid(workflow, jobs)
    ):
        return None
    return _scoped_job_name(raw_job)
