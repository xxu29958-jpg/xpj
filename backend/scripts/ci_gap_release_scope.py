"""Release APK scope policy helpers for the CI gap audit."""

from __future__ import annotations

import pathlib
import re

_MISSING_WORKFLOW_VIOLATION = "required workflow missing from CI gap scan"
_SCOPE_POLICY_VIOLATION = "Android release APK builds must be path-gated for non-Android changes"
_EXPECTED_WORKFLOWS = ((".github", "ci.yml", True), (".gitea", "windows-ci.yml", False))
_RELEASE_IF = "steps.release-apk-scope.outputs.release_apk_required == 'true'"
_RELEASE_TASKS = (":app:assembleGrayRelease", ":app:assembleInternalRelease")


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _active_lines(block: str) -> list[str]:
    return [line for line in block.splitlines() if not line.lstrip().startswith("#")]


def _step_blocks(path: pathlib.Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip()
        if not stripped.startswith("- name:"):
            index += 1
            continue
        indent = _line_indent(line)
        block = [line]
        index += 1
        while index < len(lines):
            child = lines[index]
            if child.strip() and _line_indent(child) <= indent and child.lstrip().startswith("- name:"):
                break
            block.append(child)
            index += 1
        blocks.append("\n".join(block))
    return blocks


def _metadata_value(block: str, key: str) -> str | None:
    prefix = f"{key}:"
    for line in _active_lines(block):
        stripped = line.lstrip()
        if stripped.startswith(prefix):
            value = stripped.removeprefix(prefix).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                return value[1:-1]
            return value
    return None


def _has_metadata(block: str, key: str, value: str) -> bool:
    return _metadata_value(block, key) == value


def _active_text(block: str) -> str:
    return "\n".join(_active_lines(block))


def _has_release_tasks(block: str) -> bool:
    text = _active_text(block)
    return all(task in text for task in _RELEASE_TASKS)


def _github_output_write(text: str, value: str) -> bool:
    return (
        re.search(
            rf"^\s*echo\s+['\"]release_apk_required={value}['\"]\s*>>\s*"
            r'(?:"\$GITHUB_OUTPUT"|\$GITHUB_OUTPUT)(?:\s|$)',
            text,
            flags=re.MULTILINE,
        )
        is not None
    )


def _line_index(lines: list[str], pattern: str, *, start: int = 0, stop: int | None = None) -> int:
    end = len(lines) if stop is None else stop
    if end < start:
        return -1
    for index in range(start, end):
        if re.search(pattern, lines[index]):
            return index
    return -1


def _github_detect_step_valid(text: str) -> bool:
    lines = text.splitlines()
    true_output = (
        r'^\s*echo\s+["\']release_apk_required=true["\']\s*>>\s*'
        r'(?:"\$GITHUB_OUTPUT"|\$GITHUB_OUTPUT)(?:\s|$)'
    )
    false_output = (
        r'^\s*echo\s+["\']release_apk_required=false["\']\s*>>\s*'
        r'(?:"\$GITHUB_OUTPUT"|\$GITHUB_OUTPUT)(?:\s|$)'
    )
    non_pr_if = _line_index(
        lines,
        r'^\s*if\s+\[\s*"\$\{\{\s*github\.event_name\s*\}\}"\s+!=\s+"pull_request"\s+\];\s*then',
    )
    non_pr_fi = _line_index(lines, r"^\s*fi\s*$", start=non_pr_if + 1)
    non_pr_true = _line_index(lines, true_output, start=non_pr_if + 1, stop=non_pr_fi)
    non_pr_exit = _line_index(lines, r"^\s*exit\s+0\s*$", start=non_pr_true + 1, stop=non_pr_fi)
    base_line = _line_index(
        lines,
        r'^\s*base="\$\{\{\s*github\.event\.pull_request\.base\.sha\s*\}\}"',
        start=non_pr_fi + 1,
    )
    head_line = _line_index(
        lines,
        r'^\s*head="\$\{\{\s*github\.event\.pull_request\.head\.sha\s*\}\}"',
        start=base_line + 1,
    )
    changed_line = _line_index(
        lines,
        r'^\s*changed="\$\(git diff --name-only "\$\{base\}\.\.\.\$\{head\}"\)"',
        start=head_line + 1,
    )
    path_if = _line_index(
        lines,
        r"^\s*if\s+printf\s+'%s\\n'\s+\"\$changed\"\s+\|\s+grep\s+-E\s+'[^']*android/[^']*\\\.github/workflows/[^']*\\\.gitea/workflows/[^']*'\s+>/dev/null;\s*then",
        start=changed_line + 1,
    )
    path_fi = _line_index(lines, r"^\s*fi\s*$", start=path_if + 1)
    path_true = _line_index(lines, true_output, start=path_if + 1, stop=path_fi)
    path_else = _line_index(lines, r"^\s*else\s*$", start=path_true + 1, stop=path_fi)
    path_false = _line_index(lines, false_output, start=path_else + 1, stop=path_fi)
    has_required_shape = all(
        index >= 0
        for index in [
            non_pr_if,
            non_pr_true,
            non_pr_exit,
            non_pr_fi,
            base_line,
            head_line,
            changed_line,
            path_if,
            path_true,
            path_else,
            path_false,
            path_fi,
        ]
    )
    return has_required_shape and _line_index(
        lines, r"^\s*exit\b", start=non_pr_fi + 1, stop=path_fi
    ) == -1


def _has_line(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.MULTILINE) is not None


def _indexes_present(indexes: list[int]) -> bool:
    return all(index >= 0 for index in indexes)


def _gitea_helper_lines_valid(text: str) -> bool:
    helper_patterns = [
        r"^\s*function\s+Set-ReleaseApkRequired\(",
        r"^\s*\[System\.IO\.File\]::AppendAllText\(",
        r"^\s*\$env:GITHUB_OUTPUT,",
        r'^\s*"release_apk_required=\$value`n",',
        r"^\s*\[System\.Text\.UTF8Encoding\]::new\(\$false\)",
        r'^\s*\$eventName\s*=\s*"\$\{\{\s*github\.event_name\s*\}\}"',
        r'^\s*\$refName\s*=\s*"\$\{\{\s*github\.ref_name\s*\}\}"',
    ]
    return all(_has_line(text, pattern) for pattern in helper_patterns)


def _gitea_main_gate_indexes(lines: list[str], true_call: str) -> tuple[list[int], int]:
    main_if = _line_index(
        lines,
        r'^\s*if\s*\(\$eventName\s+-eq\s+"workflow_dispatch"\s+-or\s+\$refName\s+-eq\s+"main"\)\s*{',
    )
    main_close = _line_index(lines, r"^\s*}\s*$", start=main_if + 1)
    main_true = _line_index(lines, true_call, start=main_if + 1, stop=main_close)
    main_exit = _line_index(lines, r"^\s*exit\s+0\s*$", start=main_true + 1, stop=main_close)
    return [main_if, main_true, main_exit, main_close], main_close


def _gitea_diff_gate_indexes(lines: list[str], start: int) -> tuple[list[int], int]:
    primary_diff = _line_index(
        lines,
        r"^\s*\$changed\s*=\s*@\(git diff --name-only origin/main\.\.\.HEAD\)",
        start=start + 1,
    )
    fallback_if = _line_index(
        lines,
        r"^\s*if\s*\(\$LASTEXITCODE\s+-ne\s+0\)\s*{",
        start=primary_diff + 1,
    )
    fallback_diff = _line_index(
        lines,
        r"^\s*\$changed\s*=\s*@\(git diff --name-only origin/main HEAD\)",
        start=fallback_if + 1,
    )
    fallback_close = _line_index(lines, r"^\s*}\s*$", start=fallback_diff + 1)
    throw_if = _line_index(
        lines,
        r"^\s*if\s*\(\$LASTEXITCODE\s+-ne\s+0\)\s*{",
        start=fallback_close + 1,
    )
    throw_line = _line_index(lines, r'^\s*throw\s+"Unable to compute changed files', start=throw_if + 1)
    throw_close = _line_index(lines, r"^\s*}\s*$", start=throw_line + 1)
    return [
        primary_diff,
        fallback_if,
        fallback_diff,
        fallback_close,
        throw_if,
        throw_line,
        throw_close,
    ], throw_close


def _gitea_path_gate_indexes(
    lines: list[str], start: int, true_call: str, false_call: str
) -> tuple[list[int], int]:
    release_relevant = _line_index(
        lines,
        r"^\s*\$releaseRelevant\s*=\s*\$changed\s*\|\s*Where-Object\s*{",
        start=start + 1,
    )
    path_match = _line_index(
        lines,
        r"^\s*\$_\s+-match\s+'[^']*android/[^']*\\\.github/workflows/[^']*\\\.gitea/workflows/[^']*'",
        start=release_relevant + 1,
    )
    relevant_close = _line_index(lines, r"^\s*}\s*\|\s*Select-Object\s+-First\s+1\s*$", start=path_match + 1)
    path_if = _line_index(lines, r"^\s*if\s*\(\$releaseRelevant\)\s*{", start=relevant_close + 1)
    path_close = _line_index(lines, r"^\s*}\s*$", start=path_if + 1)
    path_true = _line_index(lines, true_call, start=path_if + 1, stop=path_close)
    path_else = _line_index(lines, r"^\s*}\s*else\s*{\s*$", start=path_true + 1, stop=path_close)
    path_false = _line_index(lines, false_call, start=path_else + 1, stop=path_close)
    return [
        release_relevant,
        path_match,
        relevant_close,
        path_if,
        path_true,
        path_else,
        path_false,
        path_close,
    ], path_close


def _gitea_detect_step_valid(text: str) -> bool:
    if not _gitea_helper_lines_valid(text):
        return False
    lines = text.splitlines()
    true_call = r'^\s*Set-ReleaseApkRequired\s+"true"\s*$'
    false_call = r'^\s*Set-ReleaseApkRequired\s+"false"\s*$'
    main_indexes, main_close = _gitea_main_gate_indexes(lines, true_call)
    diff_indexes, diff_close = _gitea_diff_gate_indexes(lines, main_close)
    path_indexes, path_close = _gitea_path_gate_indexes(lines, diff_close, true_call, false_call)
    has_required_shape = _indexes_present(main_indexes + diff_indexes + path_indexes)
    return has_required_shape and _line_index(
        lines, r"^\s*exit\b", start=main_close + 1, stop=path_close
    ) == -1


def _detect_step_valid(block: str, *, github: bool) -> bool:
    text = _active_text(block)
    return (
        _has_metadata(block, "id", "release-apk-scope")
        and (_github_detect_step_valid(text) if github else _gitea_detect_step_valid(text))
    )


def _workflow_scope_valid(path: pathlib.Path, *, github: bool) -> bool:
    blocks = _step_blocks(path)
    release_blocks = [block for block in blocks if _has_release_tasks(block)]
    detect_blocks = [block for block in blocks if _has_metadata(block, "id", "release-apk-scope")]
    if not release_blocks or not any(_detect_step_valid(block, github=github) for block in detect_blocks):
        return False
    return all(_has_metadata(block, "if", _RELEASE_IF) for block in release_blocks)


def _find_workflow(workflow_paths: set[pathlib.Path], root: str, name: str) -> pathlib.Path | None:
    matches = [
        path
        for path in workflow_paths
        if root in path.parts and "workflows" in path.parts and path.name == name
    ]
    return sorted(matches, key=str)[0] if matches else None


def release_apk_scope_policy_violations(workflow_paths: set[pathlib.Path]) -> list[str]:
    violations: list[str] = []
    for root, name, github in _EXPECTED_WORKFLOWS:
        label = f"{root}/workflows/{name}"
        path = _find_workflow(workflow_paths, root, name)
        if path is None:
            violations.append(f"{label}: {_MISSING_WORKFLOW_VIOLATION}")
        elif not _workflow_scope_valid(path, github=github):
            violations.append(f"{label}: {_SCOPE_POLICY_VIOLATION}")
    return violations
