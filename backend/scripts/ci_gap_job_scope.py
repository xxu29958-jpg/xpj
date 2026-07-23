"""Prove fail-closed heavy-job scope wiring in GitHub and Gitea CI."""

from __future__ import annotations

import pathlib
import re

from ci_gap_shell import shell_tokens
from ci_gap_trigger_scope import CI_HEAVY_SCOPES
from ci_gap_workflow_conditions import allows_failure

HEAVY_JOB_SCOPES = frozenset(CI_HEAVY_SCOPES)
_GITHUB_SCOPE_OUTPUTS = {
    scope: f"${{{{ steps.scope.outputs.{scope} }}}}" for scope in HEAVY_JOB_SCOPES
}
_GITHUB_SCOPE_OUTPUTS["postgres_matrix"] = "${{ steps.scope.outputs.postgres_matrix }}"
_GITHUB_SCOPE_OUTPUTS["qualification_sha"] = "${{ steps.qualification.outputs.sha }}"
_GITHUB_SCOPE_OUTPUTS["qualification_source_sha"] = (
    "${{ steps.qualification.outputs.source_sha }}"
)
_GITEA_SCOPE_OUTPUTS = {
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
_GITEA_SCOPE_COMMAND = (
    'python -E -S backend\\scripts\\ci_scope.py '
    '--event "$env:GITHUB_EVENT_NAME" --base "$env:SCOPE_BASE" '
    '--head "$env:SCOPE_HEAD" --output "$env:GITHUB_OUTPUT"'
)
_GITEA_SCOPE_ENV = {
    "SCOPE_BASE": "${{ github.event.before }}",
    "SCOPE_HEAD": "${{ github.sha }}",
}
_GITEA_STEP_SCOPE_CONDITION = re.compile(
    r"success\(\)\s*&&\s*\(\s*"
    r"needs\.scope\.result\s*!=\s*['\"]success['\"]"
    r"(?P<clauses>(?:\s*\|\|\s*needs\.scope\.outputs\.[a-z_]+\s*!=\s*"
    r"['\"]false['\"])+)\s*\)"
)
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
_REQUIRED_GATE_JOB = "backend"
_REQUIRED_GATE_NEEDS = (
    "scope",
    "backend_contracts",
    "backend_frozen",
    "windows_packaging",
)
_REQUIRED_GATE_ENV = {
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
_REQUIRED_GATE_ARGS = (
    "python",
    "-E",
    "-S",
    "backend/scripts/verify_backend_ci_results.py",
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


def _qualification_command_is_valid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return len(lines) == 1 and shell_tokens(lines[0]) == _QUALIFICATION_ARGS


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


def _github_scope_job_is_valid(
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
        or raw_job.get("outputs") != _GITHUB_SCOPE_OUTPUTS
    ):
        return False
    steps = raw_job.get("steps")
    if not isinstance(steps, list) or len(steps) < 4:
        return False
    checkout, setup_python, qualification, resolver = steps[:4]
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
    qualification_is_complete = (
        isinstance(qualification, dict)
        and qualification.get("name") == "Verify qualification SHA"
        and qualification.get("id") == "qualification"
        and qualification.get("env")
        == {
            "EXPECTED_SHA": "${{ github.sha }}",
            "SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
        }
        and qualification.get("if") in {None, True}
        and not allows_failure(qualification.get("continue-on-error"))
        and _step_execution_shape_is_plain(qualification, allow_env=True)
        and _qualification_command_is_valid(qualification.get("run"))
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
    return (
        checkout_is_complete
        and setup_is_complete
        and qualification_is_complete
        and resolver_is_complete
    )


def _gitea_scope_job_is_valid(
    path: pathlib.Path,
    workflow: dict[object, object],
    jobs: dict[object, object],
) -> bool:
    if ".gitea" not in path.parts or path.name != "windows-ci.yml":
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
        or raw_job.get("runs-on") != "windows-latest"
        or raw_job.get("timeout-minutes") != 5
        or raw_job.get("outputs") != _GITEA_SCOPE_OUTPUTS
    ):
        return False
    steps = raw_job.get("steps")
    if not isinstance(steps, list):
        return False
    resolvers = [step for step in steps if isinstance(step, dict) and step.get("id") == "scope"]
    if len(resolvers) != 1:
        return False
    resolver = resolvers[0]
    lines = [
        " ".join(line.strip().split())
        for line in str(resolver.get("run", "")).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return (
        resolver.get("shell") == "powershell"
        and resolver.get("env") == _GITEA_SCOPE_ENV
        and resolver.get("if") in {None, True}
        and not allows_failure(resolver.get("continue-on-error"))
        and _step_execution_shape_is_plain(resolver, allow_env=True)
        and lines
        == [
            _GITEA_SCOPE_COMMAND,
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
        ]
    )


def _scope_job_is_valid(
    path: pathlib.Path,
    workflow: dict[object, object],
    jobs: dict[object, object],
) -> bool:
    return _github_scope_job_is_valid(path, workflow, jobs) or _gitea_scope_job_is_valid(
        path, workflow, jobs
    )


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
    if not isinstance(steps, list) or len(steps) < 4:
        return False
    checkout, setup_python, qualification, step = steps[:4]
    return (
        isinstance(checkout, dict)
        and _CHECKOUT_ACTION.fullmatch(str(checkout.get("uses", ""))) is not None
        and checkout.get("if") in {None, True}
        and not allows_failure(checkout.get("continue-on-error"))
        and _step_execution_shape_is_plain(checkout)
        and isinstance(setup_python, dict)
        and _SETUP_PYTHON_ACTION.fullmatch(str(setup_python.get("uses", ""))) is not None
        and setup_python.get("with") == {"python-version": "3.11"}
        and setup_python.get("if") in {None, True}
        and not allows_failure(setup_python.get("continue-on-error"))
        and _step_execution_shape_is_plain(setup_python)
        and isinstance(qualification, dict)
        and qualification.get("name") == "Verify qualification SHA"
        and qualification.get("id") == "qualification"
        and qualification.get("env")
        == {
            "EXPECTED_SHA": "${{ github.sha }}",
            "SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
        }
        and qualification.get("if") in {None, True}
        and not allows_failure(qualification.get("continue-on-error"))
        and _step_execution_shape_is_plain(qualification, allow_env=True)
        and _qualification_command_is_valid(qualification.get("run"))
        and isinstance(step, dict)
        and step.get("name") == "Enforce required CI results"
        and step.get("if") in {None, True}
        and not allows_failure(step.get("continue-on-error"))
        and step.get("env") == _REQUIRED_GATE_ENV
        and _step_execution_shape_is_plain(step, allow_env=True)
        and isinstance(step.get("run"), str)
        and shell_tokens(str(step["run"]).strip()) == _REQUIRED_GATE_ARGS
    )


def scoped_job_protection_scope(
    path: pathlib.Path,
    workflow: dict[object, object],
    raw_job: dict[object, object],
    jobs: dict[object, object],
) -> str | None:
    if not _scope_job_is_valid(path, workflow, jobs):
        return None
    if ".github" in path.parts and not _required_gate_is_valid(workflow, jobs):
        return None
    return _scoped_job_name(raw_job)


def scoped_step_protection_scope(
    path: pathlib.Path,
    workflow: dict[object, object],
    raw_job: dict[object, object],
    raw_step: dict[object, object],
    jobs: dict[object, object],
) -> str | None:
    """Return a scope only for Gitea's exact fail-closed step contract."""
    if (
        ".gitea" not in path.parts
        or not _gitea_scope_job_is_valid(path, workflow, jobs)
        or job_needs(raw_job) != ("scope",)
        or _expression_text(raw_job.get("if")) != "always() && !cancelled()"
        or allows_failure(raw_job.get("continue-on-error"))
        or allows_failure(raw_step.get("continue-on-error"))
    ):
        return None
    match = _GITEA_STEP_SCOPE_CONDITION.fullmatch(
        _expression_text(raw_step.get("if"))
    )
    if match is None:
        return None
    scopes = re.findall(r"needs\.scope\.outputs\.([a-z_]+)", match.group("clauses"))
    if not scopes or any(scope not in HEAVY_JOB_SCOPES for scope in scopes):
        return None
    if len(scopes) == 1:
        return scopes[0]
    return "windows" if "windows" in scopes else None


def scoped_step_requires_prior_success(value: object) -> bool:
    return _GITEA_STEP_SCOPE_CONDITION.fullmatch(_expression_text(value)) is not None
