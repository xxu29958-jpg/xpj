"""Parse executable workflow commands and GitHub action references."""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from hashlib import sha256

import yaml
from ci_gap_powershell import (
    looks_like_powershell as _looks_like_powershell,
)
from ci_gap_powershell import (
    powershell_reachable_command_text as _powershell_reachable_command_text,
)
from ci_gap_trigger_scope import protected_workflow_scope as _protected_workflow_scope


@dataclass(frozen=True)
class WorkflowCommand:
    workflow: pathlib.Path
    text: str
    folded: bool = False
    job: str = ""
    step: str = ""
    shell: str = ""
    protection_scope: str = "full"
    powershell_ast_digest: str = ""


_WORKFLOW_SUFFIXES = {".yml", ".yaml"}
_SCRIPT_EXECUTING_ACTIONS = {"reactivecircus/android-emulator-runner"}


class _WorkflowLoader(yaml.SafeLoader):
    """YAML 1.2-ish loader that does not coerce the workflow key ``on`` to bool."""


_WorkflowLoader.yaml_implicit_resolvers = {
    key: list(value) for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for first_character, resolvers in _WorkflowLoader.yaml_implicit_resolvers.items():
    _WorkflowLoader.yaml_implicit_resolvers[first_character] = [
        entry for entry in resolvers if entry[0] != "tag:yaml.org,2002:bool"
    ]
_WorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _load_workflow(path: pathlib.Path) -> dict[object, object]:
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_WorkflowLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid workflow YAML: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"workflow root must be a mapping: {path}")
    return value


def _required_protection_event(path: pathlib.Path) -> str:
    # GitHub branch protection is evaluated on pull_request. The Gitea mirror's
    # protected validation lane is push-based, but workflow_dispatch alone must
    # never satisfy either platform's required-command inventory.
    return "pull_request" if ".github" in path.parts else "push"


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
        if lowered in {"true", "success()", "always()"}:
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


def _condition_guarantees_after_needs(value: object, event_name: str) -> bool:
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


def _condition_allows_event(
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


def _allows_failure(value: object) -> bool:
    if value is None or value is False:
        return False
    if value is True:
        return True
    return _strip_expression_wrapper(str(value)).strip().lower() not in {"", "false"}


def _nested_action_script(raw_step: dict[object, object]) -> object:
    action = str(raw_step.get("uses", "")).split("@", maxsplit=1)[0].lower()
    inputs = raw_step.get("with")
    if action not in _SCRIPT_EXECUTING_ACTIONS or not isinstance(inputs, dict):
        return None
    return inputs.get("script")


def _locate_workflow_dirs() -> list[pathlib.Path]:
    candidates = [
        pathlib.Path("../.github/workflows"),
        pathlib.Path("../.gitea/workflows"),
        pathlib.Path(".github/workflows"),
        pathlib.Path(".gitea/workflows"),
    ]
    found: list[pathlib.Path] = []
    for candidate in candidates:
        if candidate.is_dir():
            resolved = candidate.resolve()
            if resolved not in found:
                found.append(resolved)
    return found


def _strip_comment_lines(text: str) -> str:
    """Drop ``#``-commented lines inside a run body.

    A required command that someone disabled by commenting it out inside a
    multi-line ``run: |`` block must not satisfy the gate.
    """
    kept = [
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    ]
    return "\n".join(kept)


def _workflow_dir_list(workflow_dirs: pathlib.Path | list[pathlib.Path]) -> list[pathlib.Path]:
    if isinstance(workflow_dirs, pathlib.Path):
        return [workflow_dirs]
    return workflow_dirs


def _iter_workflow_paths(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
) -> list[pathlib.Path]:
    return sorted(
        path
        for workflow_dir in _workflow_dir_list(workflow_dirs)
        for path in workflow_dir.iterdir()
        if path.is_file() and path.suffix.lower() in _WORKFLOW_SUFFIXES
    )


def _job_default_shell(raw_job: dict[object, object]) -> str:
    defaults = raw_job.get("defaults")
    if not isinstance(defaults, dict):
        return ""
    run_defaults = defaults.get("run")
    return str(run_defaults.get("shell", "")) if isinstance(run_defaults, dict) else ""


def _job_needs(raw_job: dict[object, object]) -> tuple[str, ...] | None:
    value = raw_job.get("needs")
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else None
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return tuple(value)
    return None


def _needs_graph_is_valid(
    job_name: object,
    jobs: dict[object, object],
    *,
    visiting: set[object],
) -> bool:
    if job_name in visiting:
        return False
    raw_job = jobs.get(job_name)
    if not isinstance(raw_job, dict):
        return False
    needs = _job_needs(raw_job)
    if needs is None or any(dependency not in jobs for dependency in needs):
        return False
    visiting.add(job_name)
    valid = all(
        _needs_graph_is_valid(dependency, jobs, visiting=visiting)
        for dependency in needs
    )
    visiting.remove(job_name)
    return valid


def _protected_job_is_proven(
    job_name: object,
    jobs: dict[object, object],
    event_name: str,
    *,
    memo: dict[object, bool],
    visiting: set[object],
) -> bool:
    if job_name in memo:
        return memo[job_name]
    if job_name in visiting:
        memo[job_name] = False
        return False
    raw_job = jobs.get(job_name)
    if not isinstance(raw_job, dict) or not _condition_allows_event(
        raw_job.get("if"),
        event_name,
        require_proof=True,
    ):
        memo[job_name] = False
        return False
    needs = _job_needs(raw_job)
    if needs is None or not _needs_graph_is_valid(job_name, jobs, visiting=set()):
        memo[job_name] = False
        return False
    visiting.add(job_name)
    proven = _condition_guarantees_after_needs(
        raw_job.get("if"), event_name
    ) or all(
        _protected_job_is_proven(
            dependency,
            jobs,
            event_name,
            memo=memo,
            visiting=visiting,
        )
        for dependency in needs
    )
    visiting.remove(job_name)
    memo[job_name] = proven
    return proven


def _workflow_step_command(
    *,
    path: pathlib.Path,
    job_name: object,
    index: int,
    raw_step: dict[object, object],
    job_shell: str,
    protection_scope: str,
) -> WorkflowCommand | None:
    command = raw_step.get("run", raw_step.get("script"))
    if command is None:
        command = _nested_action_script(raw_step)
    if not isinstance(command, str):
        return None
    shell = str(raw_step.get("shell", job_shell))
    executable_text = _strip_comment_lines(command)
    is_powershell = _looks_like_powershell(shell=shell, command=executable_text)
    if is_powershell:
        executable_text = _powershell_reachable_command_text(executable_text)
    return WorkflowCommand(
        path,
        executable_text,
        folded="\n" not in command,
        job=str(job_name),
        step=str(raw_step.get("name", index)),
        shell=shell,
        protection_scope=protection_scope,
        powershell_ast_digest=(
            sha256(executable_text.encode("utf-8")).hexdigest()
            if is_powershell
            else ""
        ),
    )


def _iter_workflow_run_commands(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
    *,
    protected_only: bool = False,
) -> list[WorkflowCommand]:
    commands: list[WorkflowCommand] = []
    for path in _iter_workflow_paths(workflow_dirs):
        workflow = _load_workflow(path)
        event_name = _required_protection_event(path)
        protection_scope = "full"
        if protected_only:
            resolved_scope = _protected_workflow_scope(path, workflow, event_name)
            if resolved_scope is None:
                continue
            protection_scope = resolved_scope
        jobs = workflow.get("jobs")
        if not isinstance(jobs, dict):
            continue
        protected_job_proof: dict[object, bool] = {}
        for job_name, raw_job in jobs.items():
            if not isinstance(raw_job, dict):
                continue
            job_is_reachable = (
                _protected_job_is_proven(
                    job_name,
                    jobs,
                    event_name,
                    memo=protected_job_proof,
                    visiting=set(),
                )
                if protected_only
                else _condition_allows_event(raw_job.get("if"), event_name)
            )
            if not job_is_reachable:
                continue
            if _allows_failure(raw_job.get("continue-on-error")):
                continue
            steps = raw_job.get("steps")
            if not isinstance(steps, list):
                continue
            job_shell = _job_default_shell(raw_job)
            for index, raw_step in enumerate(steps):
                if not isinstance(raw_step, dict):
                    continue
                if not _condition_allows_event(
                    raw_step.get("if"),
                    event_name,
                    require_proof=protected_only,
                ):
                    continue
                if _allows_failure(raw_step.get("continue-on-error")):
                    continue
                parsed = _workflow_step_command(
                    path=path,
                    job_name=job_name,
                    index=index,
                    raw_step=raw_step,
                    job_shell=job_shell,
                    protection_scope=protection_scope,
                )
                if parsed is not None:
                    commands.append(parsed)
    return commands
