"""Evaluate workflow conditions and terminal contracts for CI discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SCOPED_VERIFIER = "backend/scripts/verify_scoped_ci_results.py"


def _scoped_verifier_command(
    label: str,
    scope_key: str,
    *lanes: str,
    source_lanes: tuple[str, ...] = (),
    executable: str = "python",
    script: str = _SCOPED_VERIFIER,
) -> tuple[str, ...]:
    command = [executable, "-E", "-S", script, "--label", label, "--scope-key", scope_key]
    for lane in lanes:
        command.extend(("--lane", lane))
    for lane in source_lanes:
        command.extend(("--source-lane", lane))
    return tuple(command)


@dataclass(frozen=True)
class GithubTerminalContract:
    job: str
    command: tuple[str, ...]
    shell: str | None
    scope_bindings: tuple[tuple[str, str], ...]
    lane_bindings: tuple[tuple[str, str], ...]
    qualification_shell: str | None = None
    qualification_working_directory: str | None = None
    run_defaults: tuple[tuple[str, str], ...] = ()

    def environment(self) -> dict[str, str]:
        environment = {
            "SCOPE_RESULT": "${{ needs.scope.result }}",
            "EXPECTED_SHA": "${{ github.sha }}",
            "EXPECTED_SOURCE_SHA": (
                "${{ github.event.pull_request.head.sha || github.sha }}"
            ),
            "AGGREGATOR_SHA": "${{ steps.qualification.outputs.sha }}",
            "AGGREGATOR_SOURCE_SHA": (
                "${{ steps.qualification.outputs.source_sha }}"
            ),
            "SCOPE_SHA": "${{ needs.scope.outputs.qualification_sha }}",
            "SCOPE_SOURCE_SHA": (
                "${{ needs.scope.outputs.qualification_source_sha }}"
            ),
        }
        if self.shell is None:
            environment.update({"BASH_ENV": "", "ENV": ""})
        for key, output in self.scope_bindings:
            environment[key] = f"${{{{ needs.scope.outputs.{output} }}}}"
        for dependency, prefix in self.lane_bindings:
            environment[f"{prefix}_RESULT"] = f"${{{{ needs.{dependency}.result }}}}"
            environment[f"{prefix}_SHA"] = (
                f"${{{{ needs.{dependency}.outputs.qualification_sha }}}}"
            )
            environment[f"{prefix}_SOURCE_SHA"] = (
                f"${{{{ needs.{dependency}.outputs.qualification_source_sha }}}}"
            )
        return environment

    def job_defaults(self) -> dict[str, dict[str, str]] | None:
        return {"run": dict(self.run_defaults)} if self.run_defaults else None


_BACKEND_TERMINAL = GithubTerminalContract(
    job="backend",
    command=("python", "-E", "-S", "backend/scripts/verify_backend_ci_results.py"),
    shell=None,
    scope_bindings=(
        ("BACKEND_FROZEN_SCOPE", "backend_frozen"),
        ("WINDOWS_SCOPE", "windows"),
    ),
    lane_bindings=(
        ("backend_contracts", "BACKEND_CONTRACTS"),
        ("backend_frozen", "BACKEND_FROZEN"),
        ("windows_packaging", "WINDOWS_PACKAGING"),
    ),
)

_WINDOWS_TERMINAL = GithubTerminalContract(
    job="windows_packaging",
    command=_scoped_verifier_command(
        "Windows release packaging",
        "WINDOWS_SCOPE",
        "VNEXT",
        "BUILD",
        source_lanes=("BUILD",),
    ),
    shell=None,
    scope_bindings=(("WINDOWS_SCOPE", "windows"),),
    lane_bindings=(
        ("windows_vnext_lifecycle", "VNEXT"),
        ("windows_packaging_build", "BUILD"),
    ),
)

GITHUB_TERMINAL_JOBS = {
    ("ci.yml", "postgres"): GithubTerminalContract(
        job="backend-postgres",
        command=_scoped_verifier_command(
            "PostgreSQL", "POSTGRES_SCOPE", "ORDINARY", "REAL_DB", "RECOVERY"
        ),
        shell=None,
        scope_bindings=(("POSTGRES_SCOPE", "postgres"),),
        lane_bindings=(
            ("backend_postgres_ordinary", "ORDINARY"),
            ("backend_postgres_real_db", "REAL_DB"),
            ("backend_postgres_recovery", "RECOVERY"),
        ),
    ),
    ("ci.yml", "backend_frozen"): _BACKEND_TERMINAL,
    ("ci.yml", "desktop"): GithubTerminalContract(
        job="desktop-manager",
        command=_scoped_verifier_command(
            "Desktop",
            "DESKTOP_SCOPE",
            executable=".\\.ci-venv\\Scripts\\python.exe",
            script="..\\backend\\scripts\\verify_scoped_ci_results.py",
        ),
        shell="powershell",
        scope_bindings=(("DESKTOP_SCOPE", "desktop"),),
        lane_bindings=(),
        qualification_shell="bash",
        qualification_working_directory="${{ github.workspace }}",
        run_defaults=(
            ("shell", "powershell"),
            ("working-directory", "desktop"),
        ),
    ),
    ("ci.yml", "android"): GithubTerminalContract(
        job="android",
        command=_scoped_verifier_command(
            "Android", "ANDROID_SCOPE", "FAST", "DEBUG_APK", "RELEASE_APK", "SCA"
        ),
        shell=None,
        scope_bindings=(("ANDROID_SCOPE", "android"),),
        lane_bindings=(
            ("android_fast", "FAST"),
            ("android_apk_debug", "DEBUG_APK"),
            ("android_apk_release", "RELEASE_APK"),
            ("android_sca", "SCA"),
        ),
        qualification_working_directory="${{ github.workspace }}",
    ),
    ("ci.yml", "windows"): _WINDOWS_TERMINAL,
    ("codeql.yml", "android"): GithubTerminalContract(
        job="analyze-android",
        command=_scoped_verifier_command(
            "CodeQL", "ANDROID_SCOPE", "EXECUTION"
        ),
        shell=None,
        scope_bindings=(("ANDROID_SCOPE", "android"),),
        lane_bindings=(("analyze-android-execution", "EXECUTION"),),
    ),
    ("android-connected-test.yml", "android"): GithubTerminalContract(
        job="connected",
        command=_scoped_verifier_command("Connected", "ANDROID_SCOPE", "EXECUTION"),
        shell=None,
        scope_bindings=(("ANDROID_SCOPE", "android"),),
        lane_bindings=(("connected_execution", "EXECUTION"),),
    ),
}


def _strip_expression_wrapper(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("${{") and stripped.endswith("}}"):
        return stripped[3:-2].strip()
    return stripped


def _strip_outer_condition_parentheses(value: str) -> str:
    stripped = value.strip()
    while stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1].strip()
    return stripped


def _condition_branch_is_proven(branch: str, event_name: str) -> bool:
    comparison = re.compile(
        r"github\.event_name\s*(==|!=)\s*(['\"])([^'\"]+)\2",
        re.IGNORECASE,
    )
    predicates = [
        _strip_outer_condition_parentheses(predicate)
        for predicate in re.split(r"&&", branch)
    ]
    if not predicates:
        return False
    for predicate in predicates:
        lowered = predicate.lower()
        if lowered in {"true", "success()", "always()", "!cancelled()"}:
            continue
        match = comparison.fullmatch(predicate)
        if match is None:
            return False
        equal = event_name == match.group(3)
        if (match.group(1) == "==" and not equal) or (
            match.group(1) == "!=" and equal
        ):
            return False
    return True


def _condition_is_proven_for_event(expression: str, event_name: str) -> bool:
    return any(
        _condition_branch_is_proven(branch, event_name)
        for branch in re.split(r"\|\|", expression)
    )


def condition_guarantees_after_needs(value: object, event_name: str) -> bool:
    if value is None or value is False:
        return False
    expression = _strip_expression_wrapper(str(value))
    normalized = re.sub(r"\s+", " ", expression).strip()
    return any(
        re.search(r"(?i)\balways\s*\(\s*\)", branch) is not None
        and _condition_branch_is_proven(branch, event_name)
        for branch in re.split(r"\|\|", normalized)
    )


def _condition_may_allow_event(normalized: str, event_name: str) -> bool:
    if "github.event_name" not in normalized:
        return True

    comparison = re.compile(
        r"github\.event_name\s*(==|!=)\s*(['\"])([^'\"]+)\2",
        re.IGNORECASE,
    )
    for branch in re.split(r"\|\|", normalized):
        matches = list(comparison.finditer(branch))
        if not matches:
            if "github.event_name" in branch:
                continue
            if not re.search(r"\bfalse\b|failure\(\)|cancelled\(\)", branch, re.IGNORECASE):
                return True
            continue
        if re.search(r"!\s*\([^)]*github\.event_name", branch, re.IGNORECASE):
            continue
        if re.search(r"\bfalse\b|failure\(\)|cancelled\(\)", branch, re.IGNORECASE):
            continue
        permits = True
        for match in matches:
            equal = event_name == match.group(3)
            if (match.group(1) == "==" and not equal) or (
                match.group(1) == "!=" and equal
            ):
                permits = False
                break
        if permits:
            return True
    return False


def condition_allows_event(
    value: object,
    event_name: str,
    *,
    require_proof: bool = False,
) -> bool:
    if value is None or value is True:
        return True
    if value is False:
        return False
    expression = _strip_expression_wrapper(str(value))
    normalized = re.sub(r"\s+", " ", expression).strip()
    if normalized.lower() in {"", "true", "success()", "always()"}:
        return True
    if normalized.lower() in {"false", "failure()", "cancelled()"}:
        return False
    if require_proof:
        return _condition_is_proven_for_event(normalized, event_name)
    return _condition_may_allow_event(normalized, event_name)


def allows_failure(value: object) -> bool:
    if value is None or value is False:
        return False
    if value is True:
        return True
    return _strip_expression_wrapper(str(value)).strip().lower() not in {"", "false"}
