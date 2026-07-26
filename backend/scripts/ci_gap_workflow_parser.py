"""Parse executable workflow commands and GitHub action references."""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from hashlib import sha256

import yaml
from ci_gap_job_scope import job_needs as _job_needs
from ci_gap_job_scope import scoped_job_protection_scope as _scoped_job_protection_scope
from ci_gap_job_scope import scoped_step_protection_scope as _scoped_step_protection_scope
from ci_gap_job_scope import (
    scoped_step_requires_prior_success as _scoped_step_requires_prior_success,
)
from ci_gap_powershell import (
    looks_like_powershell as _looks_like_powershell,
)
from ci_gap_powershell import (
    powershell_reachable_command_text as _powershell_reachable_command_text,
)
from ci_gap_trigger_scope import protected_workflow_scope as _protected_workflow_scope
from ci_gap_trigger_scope import workflow_action_requires_prior_success
from ci_gap_workflow_conditions import allows_failure as _allows_failure
from ci_gap_workflow_conditions import condition_allows_event as _condition_allows_event
from ci_gap_workflow_conditions import (
    condition_guarantees_after_needs as _condition_guarantees_after_needs,
)


@dataclass(frozen=True)
class WorkflowCommand:
    workflow: pathlib.Path
    text: str
    folded: bool = False
    job: str = ""
    step: str = ""
    step_index: int = -1
    shell: str = ""
    protection_scope: str = "full"
    powershell_ast_digest: str = ""
    step_id: str = ""
    environment: tuple[tuple[str, str], ...] = ()
    source_text: str = ""


@dataclass(frozen=True)
class WorkflowAction:
    workflow: pathlib.Path
    uses: str
    inputs: tuple[tuple[str, str], ...]
    job: str = ""
    step: str = ""
    step_index: int = -1
    requires_prior_success: bool = True
    protection_scope: str = "full"
    environment: tuple[tuple[str, str], ...] = ()


WorkflowStep = tuple[
    pathlib.Path,
    object,
    int,
    dict[object, object],
    str,
    str,
    tuple[tuple[str, str], ...],
]


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


def load_workflow(path: pathlib.Path) -> dict[object, object]:
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


def iter_workflow_paths(
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


def _effective_environment(*scopes: object) -> tuple[tuple[str, str], ...]:
    effective: list[tuple[str, str]] = []
    for scope in scopes:
        if isinstance(scope, dict):
            effective.extend((str(key), str(value)) for key, value in scope.items())
    return tuple(effective)


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
    environment: tuple[tuple[str, str], ...],
) -> WorkflowCommand | None:
    command = raw_step.get("run", raw_step.get("script"))
    nested_action_script = None
    if command is None:
        nested_action_script = _nested_action_script(raw_step)
        command = nested_action_script
    if not isinstance(command, str):
        return None
    if nested_action_script is not None:
        executable_lines = [
            line
            for line in _strip_comment_lines(command).splitlines()
            if line.strip()
        ]
        if len(executable_lines) != 1:
            return None
    shell = str(raw_step.get("shell", job_shell))
    source_command = command
    executable_text = _strip_comment_lines(source_command)
    is_powershell = _looks_like_powershell(shell=shell, command=executable_text)
    if is_powershell:
        executable_text = _powershell_reachable_command_text(executable_text)
    return WorkflowCommand(
        path,
        executable_text,
        folded="\n" not in source_command,
        job=str(job_name),
        step=str(raw_step.get("name", index)),
        step_index=index,
        shell=shell,
        protection_scope=protection_scope,
        powershell_ast_digest=(
            sha256(executable_text.encode("utf-8")).hexdigest()
            if is_powershell
            else ""
        ),
        step_id=str(raw_step.get("id", "")),
        environment=environment,
        source_text=_strip_comment_lines(source_command),
    )


def _job_protection_scope(
    *,
    path: pathlib.Path,
    workflow: dict[object, object],
    job_name: object,
    raw_job: dict[object, object],
    jobs: dict[object, object],
    event_name: str,
    workflow_scope: str,
    protected_only: bool,
    protected_job_proof: dict[object, bool],
) -> str | None:
    if not protected_only:
        return (
            workflow_scope
            if _condition_allows_event(raw_job.get("if"), event_name)
            else None
        )
    if _protected_job_is_proven(
        job_name,
        jobs,
        event_name,
        memo=protected_job_proof,
        visiting=set(),
    ):
        return workflow_scope
    return _scoped_job_protection_scope(path, workflow, raw_job, jobs)


def _step_protection_scope(
    *,
    path: pathlib.Path,
    workflow: dict[object, object],
    raw_job: dict[object, object],
    raw_step: dict[object, object],
    jobs: dict[object, object],
    event_name: str,
    job_scope: str,
    protected_only: bool,
) -> str | None:
    if _condition_allows_event(
        raw_step.get("if"),
        event_name,
        require_proof=protected_only,
    ):
        return job_scope
    return _scoped_step_protection_scope(
        path,
        workflow,
        raw_job,
        raw_step,
        jobs,
    )


def _iter_reachable_workflow_steps(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
    *,
    protected_only: bool = False,
) -> list[WorkflowStep]:
    reachable: list[WorkflowStep] = []
    for path in iter_workflow_paths(workflow_dirs):
        workflow = load_workflow(path)
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
            job_protection_scope = _job_protection_scope(
                path=path,
                workflow=workflow,
                job_name=job_name,
                raw_job=raw_job,
                jobs=jobs,
                event_name=event_name,
                workflow_scope=protection_scope,
                protected_only=protected_only,
                protected_job_proof=protected_job_proof,
            )
            if job_protection_scope is None:
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
                step_protection_scope = _step_protection_scope(
                    path=path,
                    workflow=workflow,
                    raw_job=raw_job,
                    raw_step=raw_step,
                    jobs=jobs,
                    event_name=event_name,
                    job_scope=job_protection_scope,
                    protected_only=protected_only,
                )
                if step_protection_scope is None:
                    continue
                if _allows_failure(raw_step.get("continue-on-error")):
                    continue
                reachable.append(
                    (
                        path,
                        job_name,
                        index,
                        raw_step,
                        job_shell,
                        step_protection_scope,
                        _effective_environment(
                            workflow.get("env"),
                            raw_job.get("env"),
                            raw_step.get("env"),
                        ),
                    )
                )
    return reachable


def _iter_workflow_run_commands(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
    *,
    protected_only: bool = False,
) -> list[WorkflowCommand]:
    commands: list[WorkflowCommand] = []
    for path, job_name, index, raw_step, job_shell, protection_scope, environment in (
        _iter_reachable_workflow_steps(
            workflow_dirs,
            protected_only=protected_only,
        )
    ):
        parsed = _workflow_step_command(
            path=path,
            job_name=job_name,
            index=index,
            raw_step=raw_step,
            job_shell=job_shell,
            protection_scope=protection_scope,
            environment=environment,
        )
        if parsed is not None:
            commands.append(parsed)
    return commands


def _iter_workflow_actions(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
    *,
    protected_only: bool = False,
) -> list[WorkflowAction]:
    actions: list[WorkflowAction] = []
    for path, job_name, index, raw_step, _job_shell, protection_scope, environment in (
        _iter_reachable_workflow_steps(
            workflow_dirs,
            protected_only=protected_only,
        )
    ):
        uses = raw_step.get("uses")
        if not isinstance(uses, str):
            continue
        raw_inputs = raw_step.get("with")
        inputs = (
            tuple(sorted((str(key), str(value)) for key, value in raw_inputs.items()))
            if isinstance(raw_inputs, dict)
            else ()
        )
        actions.append(
            WorkflowAction(
                workflow=path,
                uses=uses,
                inputs=inputs,
                job=str(job_name),
                step=str(raw_step.get("name", index)),
                step_index=index,
                requires_prior_success=(
                    workflow_action_requires_prior_success(raw_step.get("if"))
                    or _scoped_step_requires_prior_success(raw_step.get("if"))
                ),
                protection_scope=protection_scope,
                environment=environment,
            )
        )
    return actions
