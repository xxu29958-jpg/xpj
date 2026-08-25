"""Audit installer artifact ordering and compile-hash dataflow in CI workflows."""

from __future__ import annotations

import re
from collections.abc import Callable

from ci_audit_provider import PLATFORM_WORKFLOW_PARTS
from ci_gap_required_commands import (
    REQUIRED_CI_ACTIONS_BY_PLATFORM,
    REQUIRED_CI_INVOCATIONS_BY_PLATFORM,
    REQUIRED_INSTALLER_POST_UPLOAD_INVOCATION_BY_PLATFORM,
    RequiredCommand,
)
from ci_gap_workflow_parser import WorkflowAction, WorkflowCommand

CommandSegmentReader = Callable[[list[WorkflowCommand]], list[str]]
_HASH_OUTPUT_REFERENCE = re.compile(
    r"^\$\{\{\s*steps\.([A-Za-z_][A-Za-z0-9_-]*)\.outputs\.([a-z0-9_]+)\s*\}\}$"
)
_EXPECTED_HASH_OUTPUTS = {
    "installer_expected_sha256": "installer_sha256",
    "build_provenance_expected_sha256": "build_provenance_sha256",
}
_PUBLISH_PATH_ENV = "installer_publish_path"
_VERIFY_DOWNLOAD_PATH_ENV = "installer_verify_download_path"
_EPHEMERAL_ENV_SUFFIX = "te" + "mp"
_FRESH_DOWNLOAD_DIRECTORY_LINES = (
    f"$downloadroot = if ($env:runner_{_EPHEMERAL_ENV_SUFFIX}) {{ $env:runner_{_EPHEMERAL_ENV_SUFFIX} }} else {{ $env:{_EPHEMERAL_ENV_SUFFIX} }}",
    '$downloadpath = join-path $downloadroot ("ticketbox-installer-verify-" + [guid]::newguid().tostring("n"))',
    'if (test-path -literalpath $downloadpath) { throw "installer verification directory already exists." }',
    "new-item -itemtype directory -path $downloadpath -erroraction stop | out-null",
    "if (@([system.io.directory]::enumeratefilesystementries($downloadpath)).count -ne 0) {",
    'throw "installer verification directory is not empty."',
    "}",
    "[system.io.file]::appendalltext(",
    "$env:github_env,",
    '"installer_verify_download_path=$downloadpath" + [environment]::newline,',
    "(new-object system.text.utf8encoding($false))",
    ")",
)
_PUBLISH_PATH_RESOLVER_LINES = (
    "$versiontext = get-content -literalpath app\\version.py -raw -encoding utf8",
    '$versionmatch = [regex]::match($versiontext, \'(?m)^\\s*backend_version\\s*=\\s*"([^\"]+)"\\s*$\')',
    'if (-not $versionmatch.success) { throw "cannot resolve installer publish version." }',
    '$publishpath = "dist/installer/ticketbox-setup-$($versionmatch.groups[1].value)"',
    "if (-not (test-path -literalpath $publishpath -pathtype container)) {",
    'throw "verified installer publish path is missing: $publishpath"',
    "}",
    "[system.io.file]::appendalltext(",
    "$env:github_env,",
    '"installer_publish_path=backend/$publishpath" + [environment]::newline,',
    "(new-object system.text.utf8encoding($false))",
    ")",
)


def _commands_for_platform(
    commands: list[WorkflowCommand],
    platform: str,
) -> list[WorkflowCommand]:
    workflow_part = PLATFORM_WORKFLOW_PARTS[platform]
    return [command for command in commands if workflow_part in command.workflow.parts]


def _command_matches(
    command: WorkflowCommand,
    requirement: RequiredCommand,
    segment_reader: CommandSegmentReader,
) -> bool:
    return any(requirement.matches(segment) for segment in segment_reader([command]))


def _windows_environment(items: tuple[tuple[str, str], ...]) -> dict[str, str]:
    effective: dict[str, str] = {}
    for key, value in items:
        effective[key.casefold()] = value
    return effective


def _normalized_source_lines(command: WorkflowCommand) -> tuple[str, ...]:
    return tuple(
        re.sub(r"\s+", " ", line.strip()).lower()
        for line in command.source_text.splitlines()
        if line.strip()
    )


def _hash_dataflow_is_valid(
    commands: list[WorkflowCommand],
    platform: str,
    segment_reader: CommandSegmentReader,
) -> bool:
    compile_requirement, verify_requirement = REQUIRED_CI_INVOCATIONS_BY_PLATFORM[
        platform
    ]
    post_requirement = REQUIRED_INSTALLER_POST_UPLOAD_INVOCATION_BY_PLATFORM[platform]
    compile_commands = [
        command
        for command in commands
        if _command_matches(command, compile_requirement, segment_reader)
    ]
    if len(compile_commands) != 1 or not compile_commands[0].step_id:
        return False
    compile_command = compile_commands[0]
    if not _compile_step_has_single_hash_writer(compile_command, compile_requirement):
        return False

    for requirement in (verify_requirement, post_requirement):
        verify_commands = [
            command
            for command in commands
            if _command_matches(command, requirement, segment_reader)
        ]
        if len(verify_commands) != 1:
            return False
        verify_command = verify_commands[0]
        if (
            verify_command.workflow != compile_command.workflow
            or verify_command.job != compile_command.job
            or compile_command.step_index < 0
            or verify_command.step_index <= compile_command.step_index
            or not _verify_step_has_exact_contract(verify_command, requirement)
        ):
            return False
        environment = _windows_environment(verify_command.environment)
        for variable, output in _EXPECTED_HASH_OUTPUTS.items():
            match = _HASH_OUTPUT_REFERENCE.fullmatch(
                environment.get(variable, "").strip()
            )
            if (
                match is None
                or match.group(1) != compile_command.step_id
                or match.group(2) != output
            ):
                return False
    return True


def _compile_step_has_single_hash_writer(
    command: WorkflowCommand,
    requirement: RequiredCommand,
) -> bool:
    lines = tuple(line.strip() for line in command.source_text.splitlines() if line.strip())
    return (
        len(lines) == 2
        and requirement.matches(lines[0])
        and lines[1].lower()
        == "if ($lastexitcode -ne 0) { exit $lastexitcode }"
    )


def _verify_step_has_exact_contract(
    command: WorkflowCommand,
    requirement: RequiredCommand,
) -> bool:
    lines = tuple(line.strip() for line in command.source_text.splitlines() if line.strip())
    return (
        len(lines) == 2
        and requirement.matches(lines[0])
        and lines[1].lower()
        == "if ($lastexitcode -ne 0) { exit $lastexitcode }"
    )


def _resolves_canonical_publish_path(command: WorkflowCommand) -> bool:
    return _normalized_source_lines(command) == _PUBLISH_PATH_RESOLVER_LINES


def missing_installer_hash_dataflow_by_platform(
    commands: list[WorkflowCommand],
    *,
    segment_reader: CommandSegmentReader,
    platforms: tuple[str, ...] = tuple(PLATFORM_WORKFLOW_PARTS),
) -> list[str]:
    missing: list[str] = []
    for platform in platforms:
        platform_commands = [
            command
            for command in _commands_for_platform(commands, platform)
            if command.protection_scope in {"full", "windows"}
        ]
        if not _hash_dataflow_is_valid(platform_commands, platform, segment_reader):
            missing.append(f"{platform}: installer hash output dataflow")
    return missing


def _publish_action_is_ordered(
    action: WorkflowAction,
    commands: list[WorkflowCommand],
    platform: str,
    segment_reader: CommandSegmentReader,
) -> bool:
    if not action.requires_prior_success or action.step_index < 0:
        return False
    if "upload-artifact@" in action.uses.lower():
        if _PUBLISH_PATH_ENV in _windows_environment(action.environment):
            return False
        resolvers = [
            command
            for command in commands
            if command.workflow == action.workflow
            and command.job == action.job
            and command.step_index == action.step_index - 1
            and _resolves_canonical_publish_path(command)
        ]
        if len(resolvers) != 1:
            return False
    segments: list[str] = []
    for command in sorted(commands, key=lambda item: item.step_index):
        if (
            command.workflow == action.workflow
            and command.job == action.job
            and 0 <= command.step_index < action.step_index
        ):
            segments.extend(segment_reader([command]))
    cursor = 0
    for invocation in REQUIRED_CI_INVOCATIONS_BY_PLATFORM[platform]:
        while cursor < len(segments) and not invocation.matches(segments[cursor]):
            cursor += 1
        if cursor == len(segments):
            return False
        cursor += 1
    return True


def _download_round_trip_is_ordered(
    download: WorkflowAction,
    actions: list[WorkflowAction],
    commands: list[WorkflowCommand],
    platform: str,
    segment_reader: CommandSegmentReader,
) -> bool:
    upload_requirement = next(
        requirement
        for requirement in REQUIRED_CI_ACTIONS_BY_PLATFORM[platform]
        if requirement.label == "atomic installer publish-unit artifact upload"
    )
    uploads = [
        action
        for action in actions
        if upload_requirement.matches(action.uses, action.inputs)
        and action.workflow == download.workflow
        and action.job == download.job
    ]
    if (
        len(uploads) != 1
        or not uploads[0].requires_prior_success
        or uploads[0].step_index >= download.step_index
        or _VERIFY_DOWNLOAD_PATH_ENV in _windows_environment(download.environment)
    ):
        return False
    fresh_directory_steps = [
        command
        for command in commands
        if command.workflow == download.workflow
        and command.job == download.job
        and uploads[0].step_index < command.step_index < download.step_index
        and _prepares_fresh_download_directory(command)
    ]
    if (
        len(fresh_directory_steps) != 1
        or fresh_directory_steps[0].step_index != uploads[0].step_index + 1
        or download.step_index != fresh_directory_steps[0].step_index + 1
    ):
        return False
    post_requirement = REQUIRED_INSTALLER_POST_UPLOAD_INVOCATION_BY_PLATFORM[platform]
    post_commands = [
        command
        for command in commands
        if command.workflow == download.workflow
        and command.job == download.job
        and command.step_index > download.step_index
        and _command_matches(command, post_requirement, segment_reader)
    ]
    return (
        len(post_commands) == 1
        and post_commands[0].step_index == download.step_index + 1
        and _VERIFY_DOWNLOAD_PATH_ENV
        not in _windows_environment(post_commands[0].environment)
        and _verify_step_has_exact_contract(post_commands[0], post_requirement)
    )


def _prepares_fresh_download_directory(command: WorkflowCommand) -> bool:
    return _normalized_source_lines(command) == _FRESH_DOWNLOAD_DIRECTORY_LINES


def missing_installer_publish_actions_by_platform(
    commands: list[WorkflowCommand],
    actions: list[WorkflowAction],
    *,
    segment_reader: CommandSegmentReader,
    platforms: tuple[str, ...] = tuple(PLATFORM_WORKFLOW_PARTS),
) -> list[str]:
    missing: list[str] = []
    for platform in platforms:
        workflow_part = PLATFORM_WORKFLOW_PARTS[platform]
        platform_commands = [
            command
            for command in _commands_for_platform(commands, platform)
            if command.protection_scope in {"full", "windows"}
        ]
        platform_actions = [
            action
            for action in actions
            if workflow_part in action.workflow.parts
            and action.protection_scope in {"full", "windows"}
        ]
        for required in REQUIRED_CI_ACTIONS_BY_PLATFORM[platform]:
            matching_actions = [
                action
                for action in platform_actions
                if required.matches(action.uses, action.inputs)
            ]
            ordered = len(matching_actions) == 1 and _publish_action_is_ordered(
                matching_actions[0],
                platform_commands,
                platform,
                segment_reader,
            )
            if ordered and required.label == "uploaded installer publish-unit download":
                ordered = _download_round_trip_is_ordered(
                    matching_actions[0],
                    platform_actions,
                    platform_commands,
                    platform,
                    segment_reader,
                )
            if not ordered:
                missing.append(f"{platform}: {required.label}")
    return missing
