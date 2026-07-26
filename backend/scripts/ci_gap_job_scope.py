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
_GITHUB_SCOPE_OUTPUTS["audit_base_sha"] = (
    "${{ steps.qualification.outputs.audit_base_sha }}"
)
_GITHUB_ANDROID_SCOPE_OUTPUTS = {
    "android": "${{ steps.scope.outputs.android }}",
    "qualification_sha": "${{ steps.qualification.outputs.sha }}",
    "qualification_source_sha": "${{ steps.qualification.outputs.source_sha }}",
}
_GITHUB_SCOPE_CONTRACTS = {
    "ci.yml": ("CI scope", _GITHUB_SCOPE_OUTPUTS, True),
    "codeql.yml": ("CodeQL scope", _GITHUB_ANDROID_SCOPE_OUTPUTS, False),
    "android-connected-test.yml": (
        "Connected scope",
        _GITHUB_ANDROID_SCOPE_OUTPUTS,
        False,
    ),
}
_GITHUB_TERMINAL_JOBS = {
    ("ci.yml", "postgres"): "backend-postgres",
    ("ci.yml", "backend_frozen"): "backend",
    ("ci.yml", "desktop"): "desktop-manager",
    ("ci.yml", "android"): "android",
    ("ci.yml", "windows"): "backend",
    ("codeql.yml", "android"): "analyze-android",
    ("android-connected-test.yml", "android"): "connected",
}
_SELF_TERMINAL_SCOPE_ENV = {
    "SCOPE_RESULT": "${{ needs.scope.result }}",
    "SCOPE_SHA": "${{ needs.scope.outputs.qualification_sha }}",
    "SCOPE_SOURCE_SHA": "${{ needs.scope.outputs.qualification_source_sha }}",
    "EXPECTED_SHA": "${{ github.sha }}",
    "EXPECTED_SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
}
_SELF_TERMINAL_SCOPE_COMMAND = shell_tokens(
    """set -euo pipefail
test "$SCOPE_RESULT" = "success"
test "$SCOPE_SHA" = "$EXPECTED_SHA"
test "$SCOPE_SOURCE_SHA" = "$EXPECTED_SOURCE_SHA"
"""
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
_SCOPE_QUALIFICATION_ARGS = (*_QUALIFICATION_ARGS, "--audit-base")
_GITHUB_QUALIFICATION_ENV = {
    "EXPECTED_SHA": "${{ github.sha }}",
    "SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
    "XPJ_AUDIT_DEFAULT_BRANCH": "${{ github.event.repository.default_branch }}",
    "XPJ_AUDIT_DEFAULT_REF": (
        "refs/remotes/origin/${{ github.event.repository.default_branch }}"
    ),
    "XPJ_AUDIT_BASE_REF": (
        "${{ github.event_name == 'pull_request' && "
        "github.event.pull_request.base.sha || github.event_name == 'push' && "
        "github.event.before || '' }}"
    ),
}


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


def _qualification_command_is_valid(
    value: object,
    *,
    resolves_audit_base: bool = False,
) -> bool:
    if not isinstance(value, str):
        return False
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    expected = _SCOPE_QUALIFICATION_ARGS if resolves_audit_base else _QUALIFICATION_ARGS
    return len(lines) == 1 and shell_tokens(lines[0]) == expected


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


def _github_qualification_step_is_valid(
    raw_step: object,
    *,
    resolves_audit_base: bool,
) -> bool:
    expected_environment = (
        _GITHUB_QUALIFICATION_ENV
        if resolves_audit_base
        else {
            "EXPECTED_SHA": "${{ github.sha }}",
            "SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
        }
    )
    return (
        isinstance(raw_step, dict)
        and raw_step.get("name") == "Verify qualification SHA"
        and raw_step.get("id") == "qualification"
        and raw_step.get("env") == expected_environment
        and raw_step.get("if") in {None, True}
        and not allows_failure(raw_step.get("continue-on-error"))
        and _step_execution_shape_is_plain(raw_step, allow_env=True)
        and _qualification_command_is_valid(
            raw_step.get("run"),
            resolves_audit_base=resolves_audit_base,
        )
    )


def _github_scope_resolver_step_is_valid(raw_step: object) -> bool:
    return (
        isinstance(raw_step, dict)
        and raw_step.get("id") == "scope"
        and raw_step.get("shell") == "bash"
        and raw_step.get("if") in {None, True}
        and not allows_failure(raw_step.get("continue-on-error"))
        and _step_execution_shape_is_plain(raw_step)
        and _bash_script_text(raw_step.get("run")) == _SCOPE_COMMAND
    )


def _github_scope_job_is_valid(
    path: pathlib.Path,
    workflow: dict[object, object],
    jobs: dict[object, object],
) -> bool:
    if ".github" not in path.parts:
        return False
    contract = _GITHUB_SCOPE_CONTRACTS.get(path.name)
    if contract is None:
        return False
    expected_name, expected_outputs, resolves_audit_base = contract
    raw_job = jobs.get("scope")
    if (
        not isinstance(raw_job, dict)
        or not _workflow_execution_shape_is_plain(workflow)
        or not _job_execution_shape_is_plain(raw_job)
        or job_needs(raw_job) != ()
        or raw_job.get("if") not in {None, True}
        or allows_failure(raw_job.get("continue-on-error"))
        or raw_job.get("name") != expected_name
        or raw_job.get("runs-on") != "ubuntu-latest"
        or raw_job.get("timeout-minutes") != 5
        or raw_job.get("outputs") != expected_outputs
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
    return (
        checkout_is_complete
        and setup_is_complete
        and _github_qualification_step_is_valid(
            qualification,
            resolves_audit_base=resolves_audit_base,
        )
        and _github_scope_resolver_step_is_valid(resolver)
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


def _terminal_gate_consumes_dependency(
    raw_job: dict[object, object],
    dependency: str,
) -> bool:
    required_values = {
        f"${{{{ needs.{dependency}.result }}}}",
        f"${{{{ needs.{dependency}.outputs.qualification_sha }}}}",
        f"${{{{ needs.{dependency}.outputs.qualification_source_sha }}}}",
        "${{ github.sha }}",
        "${{ github.event.pull_request.head.sha || github.sha }}",
    }
    for step in raw_job.get("steps", []):
        if (
            not isinstance(step, dict)
            or step.get("if") not in {None, True}
            or allows_failure(step.get("continue-on-error"))
            or not _step_execution_shape_is_plain(step, allow_env=True)
        ):
            continue
        environment = step.get("env")
        if not isinstance(environment, dict):
            continue
        values = {str(value) for value in environment.values()}
        if required_values <= values and str(step.get("run", "")).strip():
            return True
    return False


def _self_terminal_enforces_scope(raw_job: dict[object, object]) -> bool:
    environment = raw_job.get("env")
    if (
        any(
            raw_job.get(field) is not None
            for field in ("container", "services", "strategy")
        )
        or (
            isinstance(environment, dict)
            and {"BASH_ENV", "ENV"}.intersection(map(str, environment))
        )
    ):
        return False
    gates = [
        step
        for step in raw_job.get("steps", [])
        if isinstance(step, dict)
        and _expression_text(step.get("if")) == "always() && !cancelled()"
        and step.get("shell") == "bash"
        and step.get("env") == _SELF_TERMINAL_SCOPE_ENV
        and not allows_failure(step.get("continue-on-error"))
        and _step_execution_shape_is_plain(step, allow_env=True)
        and shell_tokens(str(step.get("run", ""))) == _SELF_TERMINAL_SCOPE_COMMAND
    ]
    return len(gates) == 1


def _terminal_gate_protects_job(
    path: pathlib.Path,
    scope: str,
    job_name: str,
    jobs: dict[object, object],
) -> bool:
    terminal_name = _GITHUB_TERMINAL_JOBS.get((path.name, scope))
    if terminal_name is None:
        return False
    terminal = jobs.get(terminal_name)
    if not isinstance(terminal, dict):
        return False
    if terminal_name == job_name:
        return _self_terminal_enforces_scope(terminal)
    return (
        _job_execution_shape_is_plain(terminal)
        and _expression_text(terminal.get("if")) == "always()"
        and not allows_failure(terminal.get("continue-on-error"))
        and job_name in (job_needs(terminal) or ())
        and _terminal_gate_consumes_dependency(terminal, job_name)
    )


def scoped_job_protection_scope(
    path: pathlib.Path,
    workflow: dict[object, object],
    job_name: object,
    raw_job: dict[object, object],
    jobs: dict[object, object],
) -> str | None:
    if not _scope_job_is_valid(path, workflow, jobs):
        return None
    scope = _scoped_job_name(raw_job)
    if scope is None:
        return None
    if ".github" in path.parts and not _terminal_gate_protects_job(
        path,
        scope,
        str(job_name),
        jobs,
    ):
        return None
    return scope


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
