"""GitHub external-action pin policy for the CI gap audit."""

from __future__ import annotations

import pathlib
import re

_WORKFLOW_SUFFIXES = {".yml", ".yaml"}
_EXTERNAL_USES_SHA = re.compile(
    r"^[^\s@/]+/[^\s@/]+(?:/[^\s@]+)*@[0-9a-fA-F]{40}$"
)


def _workflow_dir_list(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
) -> list[pathlib.Path]:
    return [workflow_dirs] if isinstance(workflow_dirs, pathlib.Path) else workflow_dirs


def _iter_workflow_paths(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
) -> list[pathlib.Path]:
    return sorted(
        path
        for workflow_dir in _workflow_dir_list(workflow_dirs)
        for path in workflow_dir.iterdir()
        if path.is_file() and path.suffix.lower() in _WORKFLOW_SUFFIXES
    )


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _strip_yaml_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return value[:index].rstrip()
    return value.strip()


def _unquote_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _read_quoted_yaml_scalar(remainder: str) -> str:
    quote = remainder[0]
    index = 1
    while index < len(remainder):
        if remainder[index] != quote:
            index += 1
            continue
        if quote == "'" and index + 1 < len(remainder) and remainder[index + 1] == quote:
            index += 2
            continue
        return remainder[: index + 1]
    return remainder


def _raw_yaml_uses_value(remainder: str) -> str:
    if remainder[:1] in {"'", '"'}:
        return _read_quoted_yaml_scalar(remainder)
    return re.split(r"\s*[,}]\s*", remainder, maxsplit=1)[0]


def _yaml_uses_values(structural: str) -> list[str]:
    key_pattern = re.compile(r"(?:^|[{,]\s*)['\"]?uses['\"]?\s*:\s*")
    return [
        _unquote_yaml_scalar(
            _strip_yaml_inline_comment(
                _raw_yaml_uses_value(structural[match.end() :].lstrip())
            )
        )
        for match in key_pattern.finditer(structural)
    ]


def _iter_yaml_uses(path: pathlib.Path) -> list[tuple[int, str]]:
    uses: list[tuple[int, str]] = []
    block_scalar_indent: int | None = None
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        indent = _line_indent(line)
        if block_scalar_indent is not None:
            if not line.strip() or indent > block_scalar_indent:
                continue
            block_scalar_indent = None
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        structural = stripped[2:].lstrip() if stripped.startswith("- ") else stripped
        uses.extend((line_number, value) for value in _yaml_uses_values(structural))
        if re.match(r"[^:#]+:\s*[>|][+-]?\s*(?:#.*)?$", structural):
            block_scalar_indent = indent
    return uses


def _is_github_workflow(path: pathlib.Path) -> bool:
    return ".github" in path.parts and "workflows" in path.parts


def github_external_uses_pin_violations(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
) -> list[str]:
    violations: list[str] = []
    for path in _iter_workflow_paths(workflow_dirs):
        if not _is_github_workflow(path):
            continue
        for line_number, value in _iter_yaml_uses(path):
            if value.startswith("./"):
                continue
            if _EXTERNAL_USES_SHA.fullmatch(value) is None:
                violations.append(
                    f"{path.name}:{line_number}: external uses ref must be exactly a "
                    f"40-hex commit SHA: {value}"
                )
    return violations
