"""Validate stable GitHub terminal gates for scope-aware CI jobs."""

from __future__ import annotations

import pathlib
import re

from ci_gap_shell import shell_tokens
from ci_gap_workflow_conditions import allows_failure

_CHECKOUT_ACTION = re.compile(r"^actions/checkout@[0-9a-f]{40}$")
_SETUP_PYTHON_ACTION = re.compile(r"^actions/setup-python@[0-9a-f]{40}$")
_QUALIFICATION_ARGS = (
    "python",
    "-E",
    "-S",
    "backend/scripts/report_qualification_sha.py",
    "--expected",
    "$EXPECTED_SHA",
    "--source",
    "$SOURCE_SHA",
    "--output",
    "$GITHUB_OUTPUT",
)
_QUALIFICATION_ENV = {
    "EXPECTED_SHA": "${{ github.sha }}",
    "SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
}
_BACKEND_GATE_NEEDS = (
    "scope",
    "backend_contracts",
    "backend_frozen",
    "windows_packaging",
)
_BACKEND_GATE_ENV = {
    "SCOPE_RESULT": "${{ needs.scope.result }}",
    "BACKEND_FROZEN_SCOPE": "${{ needs.scope.outputs.backend_frozen }}",
    "WINDOWS_SCOPE": "${{ needs.scope.outputs.windows }}",
    "BACKEND_CONTRACTS_RESULT": "${{ needs.backend_contracts.result }}",
    "BACKEND_FROZEN_RESULT": "${{ needs.backend_frozen.result }}",
    "WINDOWS_PACKAGING_RESULT": "${{ needs.windows_packaging.result }}",
    "EXPECTED_SHA": "${{ github.sha }}",
    "EXPECTED_SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
    "AGGREGATOR_SHA": "${{ steps.qualification.outputs.sha }}",
    "AGGREGATOR_SOURCE_SHA": "${{ steps.qualification.outputs.source_sha }}",
    "SCOPE_SHA": "${{ needs.scope.outputs.qualification_sha }}",
    "SCOPE_SOURCE_SHA": "${{ needs.scope.outputs.qualification_source_sha }}",
    "BACKEND_CONTRACTS_SHA": "${{ needs.backend_contracts.outputs.qualification_sha }}",
    "BACKEND_CONTRACTS_SOURCE_SHA": "${{ needs.backend_contracts.outputs.qualification_source_sha }}",
    "BACKEND_FROZEN_SHA": "${{ needs.backend_frozen.outputs.qualification_sha }}",
    "BACKEND_FROZEN_SOURCE_SHA": "${{ needs.backend_frozen.outputs.qualification_source_sha }}",
    "WINDOWS_PACKAGING_SHA": "${{ needs.windows_packaging.outputs.qualification_sha }}",
    "WINDOWS_PACKAGING_SOURCE_SHA": "${{ needs.windows_packaging.outputs.qualification_source_sha }}",
}
_CODEQL_GATE_ENV = {
    "SCOPE_RESULT": "${{ needs.scope.result }}",
    "SCOPE_SHA": "${{ needs.scope.outputs.qualification_sha }}",
    "SCOPE_SOURCE_SHA": "${{ needs.scope.outputs.qualification_source_sha }}",
    "EXPECTED_SHA": "${{ github.sha }}",
    "EXPECTED_SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
}
_CONNECTED_GATE_ENV = {
    "SCOPE_RESULT": "${{ needs.scope.result }}",
    "ANDROID_SCOPE": "${{ needs.scope.outputs.android }}",
    "EXECUTION_RESULT": "${{ needs.connected_execution.result }}",
    "EXPECTED_SHA": "${{ github.sha }}",
    "EXPECTED_SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
    "SCOPE_SHA": "${{ needs.scope.outputs.qualification_sha }}",
    "SCOPE_SOURCE_SHA": "${{ needs.scope.outputs.qualification_source_sha }}",
    "EXECUTION_SHA": "${{ needs.connected_execution.outputs.qualification_sha }}",
    "EXECUTION_SOURCE_SHA": (
        "${{ needs.connected_execution.outputs.qualification_source_sha }}"
    ),
    "AGGREGATOR_SHA": "${{ steps.qualification.outputs.sha }}",
    "AGGREGATOR_SOURCE_SHA": "${{ steps.qualification.outputs.source_sha }}",
}


def _expression_text(value: object) -> str:
    expression = str(value).strip()
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2].strip()
    return re.sub(r"\s+", " ", expression)


def _bash_script_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(
        line.strip()
        for line in value.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _job_needs(raw_job: dict[object, object]) -> tuple[str, ...] | None:
    value = raw_job.get("needs")
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else None
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return tuple(value)
    return None


def _step_is_plain(raw_step: dict[object, object], *, allow_env: bool = False) -> bool:
    return (
        (allow_env or raw_step.get("env") is None)
        and raw_step.get("working-directory") is None
        and raw_step.get("timeout-minutes") is None
    )


def _qualification_step_is_valid(raw_step: object) -> bool:
    return (
        isinstance(raw_step, dict)
        and raw_step.get("name") == "Verify qualification SHA"
        and raw_step.get("id") == "qualification"
        and raw_step.get("env") == _QUALIFICATION_ENV
        and raw_step.get("if") in {None, True}
        and not allows_failure(raw_step.get("continue-on-error"))
        and _step_is_plain(raw_step, allow_env=True)
        and shell_tokens(str(raw_step.get("run", "")).strip())
        == _QUALIFICATION_ARGS
    )


def _backend_gate_is_valid(
    workflow: dict[object, object],
    jobs: dict[object, object],
) -> bool:
    raw_job = jobs.get("backend")
    if (
        not isinstance(raw_job, dict)
        or workflow.get("env") is not None
        or workflow.get("defaults") is not None
        or raw_job.get("name") != "Backend"
        or _job_needs(raw_job) != _BACKEND_GATE_NEEDS
        or _expression_text(raw_job.get("if")) != "always()"
        or allows_failure(raw_job.get("continue-on-error"))
        or raw_job.get("runs-on") != "ubuntu-latest"
        or raw_job.get("timeout-minutes") != 5
    ):
        return False
    steps = raw_job.get("steps")
    if not isinstance(steps, list) or len(steps) < 4:
        return False
    checkout, setup_python, qualification, gate = steps[:4]
    return (
        isinstance(checkout, dict)
        and _CHECKOUT_ACTION.fullmatch(str(checkout.get("uses", ""))) is not None
        and _step_is_plain(checkout)
        and isinstance(setup_python, dict)
        and _SETUP_PYTHON_ACTION.fullmatch(str(setup_python.get("uses", ""))) is not None
        and setup_python.get("with") == {"python-version": "3.11"}
        and _step_is_plain(setup_python)
        and _qualification_step_is_valid(qualification)
        and isinstance(gate, dict)
        and gate.get("name") == "Enforce required CI results"
        and gate.get("env") == _BACKEND_GATE_ENV
        and not allows_failure(gate.get("continue-on-error"))
        and _step_is_plain(gate, allow_env=True)
        and shell_tokens(str(gate.get("run", "")).strip())
        == (
            "python",
            "-E",
            "-S",
            "backend/scripts/verify_backend_ci_results.py",
        )
    )


def _codeql_gate_is_valid(jobs: dict[object, object]) -> bool:
    raw_job = jobs.get("analyze-android")
    if (
        not isinstance(raw_job, dict)
        or raw_job.get("name") != "Analyze (java-kotlin)"
        or _job_needs(raw_job) != ("scope",)
        or allows_failure(raw_job.get("continue-on-error"))
    ):
        return False
    gates = [
        step
        for step in raw_job.get("steps", [])
        if isinstance(step, dict)
        and step.get("name") == "Enforce CodeQL scope result"
    ]
    if len(gates) != 1:
        return False
    gate = gates[0]
    expected_script = (
        'set -euo pipefail test "$SCOPE_RESULT" = "success" '
        'test "$SCOPE_SHA" = "$EXPECTED_SHA" '
        'test "$SCOPE_SOURCE_SHA" = "$EXPECTED_SOURCE_SHA"'
    )
    return (
        _expression_text(gate.get("if")) == "always() && !cancelled()"
        and gate.get("shell") == "bash"
        and gate.get("env") == _CODEQL_GATE_ENV
        and not allows_failure(gate.get("continue-on-error"))
        and _step_is_plain(gate, allow_env=True)
        and _bash_script_text(gate.get("run")) == expected_script
    )


def _connected_gate_is_valid(jobs: dict[object, object]) -> bool:
    raw_job = jobs.get("connected")
    if (
        not isinstance(raw_job, dict)
        or raw_job.get("name") != "Connected (emulator)"
        or _job_needs(raw_job) != ("scope", "connected_execution")
        or _expression_text(raw_job.get("if")) != "always()"
        or allows_failure(raw_job.get("continue-on-error"))
        or raw_job.get("runs-on") != "ubuntu-latest"
        or raw_job.get("timeout-minutes") != 5
    ):
        return False
    steps = raw_job.get("steps")
    if not isinstance(steps, list):
        return False
    qualifications = [
        step for step in steps if _qualification_step_is_valid(step)
    ]
    gates = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Enforce Connected result"
    ]
    if len(qualifications) != 1 or len(gates) != 1:
        return False
    gate = gates[0]
    script = _bash_script_text(gate.get("run"))
    required_checks = (
        'require_equal "$SCOPE_RESULT" "success"',
        'require_equal "$SCOPE_SHA" "$EXPECTED_SHA"',
        'require_equal "$SCOPE_SOURCE_SHA" "$EXPECTED_SOURCE_SHA"',
        'require_equal "$AGGREGATOR_SHA" "$EXPECTED_SHA"',
        'require_equal "$AGGREGATOR_SOURCE_SHA" "$EXPECTED_SOURCE_SHA"',
        'if [ "$ANDROID_SCOPE" = "false" ]; then',
        'require_equal "$EXECUTION_RESULT" "skipped"',
        'require_equal "$EXECUTION_SHA" ""',
        'require_equal "$EXECUTION_SOURCE_SHA" ""',
        'require_equal "$ANDROID_SCOPE" "true"',
        'require_equal "$EXECUTION_RESULT" "success"',
        'require_equal "$EXECUTION_SHA" "$EXPECTED_SHA"',
        'require_equal "$EXECUTION_SOURCE_SHA" "$EXPECTED_SOURCE_SHA"',
    )
    return (
        gate.get("shell") == "bash"
        and gate.get("if") in {None, True}
        and gate.get("env") == _CONNECTED_GATE_ENV
        and not allows_failure(gate.get("continue-on-error"))
        and _step_is_plain(gate, allow_env=True)
        and script.startswith("set -euo pipefail require_equal()")
        and all(check in script for check in required_checks)
    )


def github_terminal_gate_is_valid(
    path: pathlib.Path,
    workflow: dict[object, object],
    jobs: dict[object, object],
) -> bool:
    validators = {
        "ci.yml": lambda: _backend_gate_is_valid(workflow, jobs),
        "codeql.yml": lambda: _codeql_gate_is_valid(jobs),
        "android-connected-test.yml": lambda: _connected_gate_is_valid(jobs),
    }
    validator = validators.get(path.name)
    return validator is not None and validator()
