"""GitHub external-action pin policy for the CI gap audit."""

from __future__ import annotations

import pathlib
import re

_WORKFLOW_SUFFIXES = {".yml", ".yaml"}
_EXTERNAL_USES_SHA = re.compile(
    r"^(?P<identity>[^\s@/]+/[^\s@/]+(?:/[^\s@]+)*)@"
    r"(?P<sha>[0-9a-fA-F]{40})$"
)
_TRUSTED_EXTERNAL_ACTIONS: dict[str, frozenset[str]] = {
    "actions/cache": frozenset({"0057852bfaa89a56745cba8c7296529d2fc39830"}),
    "actions/cache/restore": frozenset(
        {"0057852bfaa89a56745cba8c7296529d2fc39830"}
    ),
    "actions/cache/save": frozenset(
        {"0057852bfaa89a56745cba8c7296529d2fc39830"}
    ),
    "actions/checkout": frozenset(
        {"df4cb1c069e1874edd31b4311f1884172cec0e10"}
    ),
    "actions/download-artifact": frozenset(
        {"d3f86a106a0bac45b974a628896c90dbdf5c8093"}
    ),
    "actions/setup-java": frozenset(
        {"0f481fcb613427c0f801b606911222b5b6f3083a"}
    ),
    "actions/setup-python": frozenset(
        {"ece7cb06caefa5fff74198d8649806c4678c61a1"}
    ),
    "actions/upload-artifact": frozenset(
        {
            "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
            "ea165f8d65b6e75b540449e92b4886f43607fa02",
        }
    ),
    "github/codeql-action/analyze": frozenset(
        {"1ad29ea4a422cce9a242a9fae469541dcd08addc"}
    ),
    "github/codeql-action/init": frozenset(
        {"1ad29ea4a422cce9a242a9fae469541dcd08addc"}
    ),
    "gradle/actions/setup-gradle": frozenset(
        {"3f131e8634966bd73d06cc69884922b02e6faf92"}
    ),
    "reactivecircus/android-emulator-runner": frozenset(
        {"4c44018e59b437e86cdfc41da381398f93ed8808"}
    ),
}


def _workflow_dir_list(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
) -> list[pathlib.Path]:
    return [workflow_dirs] if isinstance(workflow_dirs, pathlib.Path) else workflow_dirs


def _iter_workflow_paths(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
) -> list[pathlib.Path]:
    paths: set[pathlib.Path] = set()
    for workflow_dir in _workflow_dir_list(workflow_dirs):
        paths.update(
            path
            for path in workflow_dir.iterdir()
            if path.is_file() and path.suffix.lower() in _WORKFLOW_SUFFIXES
        )
        if workflow_dir.name != "workflows" or workflow_dir.parent.name != ".github":
            continue
        actions_dir = workflow_dir.parent / "actions"
        if actions_dir.is_dir():
            paths.update(
                path
                for path in actions_dir.rglob("*")
                if path.is_file() and path.name.lower() in {"action.yml", "action.yaml"}
            )
    return sorted(paths)


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


def _is_github_automation(path: pathlib.Path) -> bool:
    if ".github" not in path.parts:
        return False
    github_index = path.parts.index(".github")
    return (
        github_index + 1 < len(path.parts)
        and path.parts[github_index + 1] in {"workflows", "actions"}
    )


def _github_relative_path(path: pathlib.Path) -> str:
    github_index = path.parts.index(".github")
    return pathlib.PurePosixPath(*path.parts[github_index:]).as_posix()


def _repository_root(path: pathlib.Path) -> pathlib.Path:
    github_dir = next(parent for parent in path.parents if parent.name == ".github")
    return github_dir.parent


def _local_action_violation(path: pathlib.Path, value: str) -> str | None:
    if not value.startswith("./.github/actions/"):
        return (
            "local action must live under the audited .github/actions tree: "
            f"{value}"
        )
    relative = pathlib.PurePosixPath(value[2:])
    if ".." in relative.parts:
        return f"local action path must not traverse directories: {value}"
    repository_root = _repository_root(path).resolve()
    actions_root = (repository_root / ".github" / "actions").resolve()
    target = (repository_root / pathlib.Path(*relative.parts)).resolve()
    try:
        target.relative_to(actions_root)
    except ValueError:
        return f"local action must resolve inside .github/actions: {value}"
    if not target.is_dir():
        return f"local action directory does not exist: {value}"
    metadata = [
        candidate
        for candidate in (target / "action.yml", target / "action.yaml")
        if candidate.is_file() and not candidate.is_symlink()
    ]
    if len(metadata) != 1:
        return f"local action must resolve to exactly one metadata file: {value}"
    return None


def _external_action_violation(value: str) -> str | None:
    match = _EXTERNAL_USES_SHA.fullmatch(value)
    if match is None:
        return f"external uses ref must be exactly a 40-hex commit SHA: {value}"
    identity = match.group("identity")
    sha = match.group("sha").lower()
    if sha not in _TRUSTED_EXTERNAL_ACTIONS.get(identity, frozenset()):
        return f"external action identity and SHA are not reviewed: {value}"
    return None


def github_external_uses_pin_violations(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
) -> list[str]:
    violations: list[str] = []
    for path in _iter_workflow_paths(workflow_dirs):
        if not _is_github_automation(path):
            continue
        for line_number, value in _iter_yaml_uses(path):
            violation = (
                _local_action_violation(path, value)
                if value.startswith("./")
                else _external_action_violation(value)
            )
            if violation is not None:
                violations.append(
                    f"{_github_relative_path(path)}:{line_number}: {violation}"
                )
    return violations
