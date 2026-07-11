"""Shell lexical helpers for the CI gap audit."""

from __future__ import annotations

import re
from dataclasses import dataclass

OUTPUT_COMMAND_PREFIXES = ("echo", "printf", "write-host", "write-output")
_SHELL_WORD_END = frozenset(" \t;&|()<>")


@dataclass(frozen=True)
class ShellHeredoc:
    marker: str
    strip_tabs: bool


def strip_inline_shell_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(line):
        if char == "\\" and not in_single:
            escaped = not escaped
            continue
        if char == "'" and not in_double and not escaped:
            in_single = not in_single
        elif char == '"' and not in_single and not escaped:
            in_double = not in_double
        elif (
            char == "#"
            and not in_single
            and not in_double
            and (index == 0 or line[index - 1].isspace() or line[index - 1] in ";&|()")
        ):
            return line[:index].rstrip()
        escaped = False
    return line


def _read_heredoc(line: str, start: int) -> tuple[int, ShellHeredoc] | None:
    index = start + 2
    strip_tabs = index < len(line) and line[index] == "-"
    index += int(strip_tabs)
    while index < len(line) and line[index] in " \t":
        index += 1
    if index >= len(line):
        return None

    quote = line[index] if line[index] in {"'", '"'} else ""
    if quote:
        end = line.find(quote, index + 1)
        if end < 0:
            return None
        marker = line[index + 1 : end]
        return end + 1, ShellHeredoc(marker, strip_tabs)

    end = index
    while end < len(line) and line[end] not in _SHELL_WORD_END:
        end += 1
    raw_marker = line[index:end]
    marker = re.sub(r"\\(.)", r"\1", raw_marker)
    return (end, ShellHeredoc(marker, strip_tabs)) if marker else None


def _heredoc_at(
    line: str,
    index: int,
    *,
    in_single: bool,
    in_double: bool,
) -> tuple[int, ShellHeredoc] | None:
    if (
        in_single
        or in_double
        or not line.startswith("<<", index)
        or line.startswith("<<<", index)
    ):
        return None
    return _read_heredoc(line, index)


def _heredocs_on_line(line: str) -> list[tuple[int, int, ShellHeredoc]]:
    matches: list[tuple[int, int, ShellHeredoc]] = []
    in_single = False
    in_double = False
    escaped = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and not in_single:
            escaped = not escaped
            index += 1
            continue
        if char == "'" and not in_double and not escaped:
            in_single = not in_single
        elif char == '"' and not in_single and not escaped:
            in_double = not in_double
        parsed = _heredoc_at(
            line,
            index,
            in_single=in_single,
            in_double=in_double,
        )
        if parsed is not None:
            end, heredoc = parsed
            matches.append((index, end, heredoc))
            index = end
            escaped = False
            continue
        escaped = False
        index += 1
    return matches


def shell_without_heredoc_literals(text: str) -> str:
    """Remove every heredoc body while preserving executable command text."""
    output: list[str] = []
    pending: list[ShellHeredoc] = []
    for line in text.splitlines():
        if pending:
            current = pending[0]
            candidate = line.lstrip("\t") if current.strip_tabs else line
            if candidate == current.marker:
                pending.pop(0)
            continue

        declarations = _heredocs_on_line(line)
        if not declarations:
            output.append(line)
            continue
        pieces: list[str] = []
        cursor = 0
        for start, end, heredoc in declarations:
            pieces.append(line[cursor:start])
            pending.append(heredoc)
            cursor = end
        pieces.append(line[cursor:])
        cleaned = "".join(pieces).strip()
        if cleaned:
            output.append(cleaned)
    return "\n".join(output)


def is_output_command(stripped_line: str) -> bool:
    return (
        bool(stripped_line)
        and stripped_line.split(maxsplit=1)[0].lower() in OUTPUT_COMMAND_PREFIXES
    )


def shell_tokens(line: str) -> tuple[str, ...]:
    return tuple(
        token.strip("'\"")
        for token in re.findall(r'''(?:"[^"]*"|'[^']*'|\S+)''', line)
    )


def _quote_state_after_char(
    char: str, *, in_single: bool, in_double: bool, escaped: bool
) -> tuple[bool, bool]:
    if char == "'" and not in_double and not escaped:
        return (not in_single, in_double)
    if char == '"' and not in_single and not escaped:
        return (in_single, not in_double)
    return (in_single, in_double)


def _is_unquoted_shell_separator(
    char: str, *, in_single: bool, in_double: bool
) -> bool:
    return not in_single and not in_double and char in ";&|"


def split_shell_command_segments(line: str) -> list[str]:
    segments: list[str] = []
    start = 0
    in_single = False
    in_double = False
    escaped = False
    skip_next = False
    for index, char in enumerate(line):
        if skip_next:
            skip_next = False
            continue
        if char == "\\" and not in_single:
            escaped = not escaped
            continue
        in_single, in_double = _quote_state_after_char(
            char,
            in_single=in_single,
            in_double=in_double,
            escaped=escaped,
        )
        if _is_unquoted_shell_separator(
            char, in_single=in_single, in_double=in_double
        ):
            segments.append(line[start:index].strip())
            skip_next = index + 1 < len(line) and line[index + 1] == char
            start = index + 2 if skip_next else index + 1
        escaped = False
    segments.append(line[start:].strip())
    return [segment for segment in segments if segment]


def has_unquoted_shell_separator(line: str) -> bool:
    in_single = False
    in_double = False
    escaped = False
    for char in line:
        if char == "\\" and not in_single:
            escaped = not escaped
            continue
        in_single, in_double = _quote_state_after_char(
            char,
            in_single=in_single,
            in_double=in_double,
            escaped=escaped,
        )
        if _is_unquoted_shell_separator(
            char, in_single=in_single, in_double=in_double
        ):
            return True
        escaped = False
    return False
