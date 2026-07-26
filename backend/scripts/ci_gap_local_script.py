"""Resolve checked-in shell entrypoints referenced by CI workflow steps."""

from __future__ import annotations

import pathlib
import shlex

_LOCAL_SHELL_LAUNCHERS = {"bash", "sh"}


def _repository_root(path: pathlib.Path) -> pathlib.Path | None:
    resolved = path.resolve()
    for parent in resolved.parents:
        if parent.name in {".github", ".gitea"}:
            return parent.parent
    return None


def _step_working_directory(raw_step: dict[object, object]) -> str:
    direct = raw_step.get("working-directory")
    if isinstance(direct, str):
        return direct
    inputs = raw_step.get("with")
    if isinstance(inputs, dict):
        nested = inputs.get("working-directory")
        if isinstance(nested, str):
            return nested
    return ""


def local_shell_script_text(
    path: pathlib.Path,
    raw_step: dict[object, object],
    command: str,
) -> str | None:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    launcher = tokens[0].replace("\\", "/").rsplit("/", maxsplit=1)[-1] if tokens else ""
    if (
        len(tokens) != 2
        or launcher not in _LOCAL_SHELL_LAUNCHERS
        or tokens[1].startswith("-")
    ):
        return None

    repository_root = _repository_root(path)
    if repository_root is None:
        return None
    working_directory = pathlib.Path(_step_working_directory(raw_step))
    if working_directory.is_absolute():
        return None
    resolved_working_directory = (repository_root / working_directory).resolve()
    if not resolved_working_directory.is_relative_to(repository_root):
        return None

    script_path = pathlib.Path(tokens[1])
    if script_path.is_absolute() or script_path.suffix.lower() != ".sh":
        return None
    resolved_script = (resolved_working_directory / script_path).resolve()
    if (
        not resolved_script.is_relative_to(repository_root)
        or not resolved_script.is_file()
    ):
        return None
    try:
        return resolved_script.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
