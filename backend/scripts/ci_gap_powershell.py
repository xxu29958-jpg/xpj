"""PowerShell reachability helpers for the CI gap audit."""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache

POWERSHELL_SHELLS = {"powershell", "pwsh"}
_SCRIPTBLOCK_TYPE = r"\[\s*(?:system\.management\.automation\.)?scriptblock\s*\]"
POWERSHELL_UNREACHABLE_STARTS = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?i)^(?:function|filter|class)\s+[\w:-]+\b",
        rf"(?i)^(?:{_SCRIPTBLOCK_TYPE}\s*)?\$[\w:]+\s*=\s*(?:{_SCRIPTBLOCK_TYPE}\s*)?\{{",
        r"(?i)^if\s*\(",
        r"(?i)^(?:while|for|foreach|switch)\s*\(",
    )
)
POWERSHELL_UNREACHABLE_SCRIPTBLOCKS = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?i)\s-(?:action|scriptblock|initializationscript|filterscript)\s*(?:\([^{}]*)?\{",
        r"(?i)(?:^|\|)\s*(?:foreach-object|where-object|%|\?)\b[^{}]*\{",
    )
)

_POWERSHELL_AST_ANALYZER = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
$source = [Console]::In.ReadToEnd()
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput(
    $source,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($null -eq $ast -or $parseErrors.Count -ne 0) {
    exit 2
}

$tryStatements = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.TryStatementAst]
}, $true))
foreach ($tryStatement in $tryStatements) {
    foreach ($catchClause in $tryStatement.CatchClauses) {
        $statements = @($catchClause.Body.Statements)
        if (
            $statements.Count -eq 0 -or
            -not ($statements[-1] -is [System.Management.Automation.Language.ThrowStatementAst])
        ) {
            exit 3
        }
    }

    if ($null -ne $tryStatement.Finally) {
        $overrides = @($tryStatement.Finally.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.ExitStatementAst] -or
            $node -is [System.Management.Automation.Language.ReturnStatementAst] -or
            $node -is [System.Management.Automation.Language.TrapStatementAst]
        }, $true))
        if ($overrides.Count -ne 0) {
            exit 4
        }
    }
}

[Console]::Out.Write('OK')
"""


def _powershell_executable() -> str | None:
    return next(
        (
            executable
            for name in ("powershell", "pwsh")
            if (executable := shutil.which(name)) is not None
        ),
        None,
    )


@lru_cache(maxsize=256)
def _powershell_ast_accepts(executable: str, text: str) -> bool:
    try:
        result = subprocess.run(
            [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _POWERSHELL_AST_ANALYZER,
            ],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout == b"OK"


def powershell_ast_propagates_failure(text: str) -> bool:
    """Parse a complete command and reject failure-suppressing try statements."""
    executable = _powershell_executable()
    return executable is not None and _powershell_ast_accepts(executable, text)


def _powershell_structure(line: str) -> str:
    output: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(line):
        if char == "`" and not in_single:
            escaped = not escaped
            output.append(" ")
            continue
        if char == "'" and not in_double and not escaped:
            in_single = not in_single
            output.append(" ")
            continue
        if char == '"' and not in_single and not escaped:
            in_double = not in_double
            output.append(" ")
            continue
        is_comment = (
            char == "#"
            and not in_single
            and not in_double
            and (index == 0 or line[index - 1].isspace())
        )
        if is_comment:
            break
        output.append(char if not in_single and not in_double else " ")
        escaped = False
    return "".join(output)


def _mask_block_comment(
    output: list[str], line: str, index: int
) -> tuple[int, bool]:
    end = line.find("#>", index)
    stop = len(line) if end < 0 else end + 2
    output[index:stop] = " " * (stop - index)
    return stop, end < 0


def _scan_code_char(
    output: list[str],
    line: str,
    index: int,
    *,
    in_single: bool,
    in_double: bool,
    escaped: bool,
) -> tuple[int, bool, bool, bool, bool, bool]:
    char = line[index]
    if char == "`" and not in_single:
        return index + 1, in_single, in_double, not escaped, False, False
    if char == "'" and not in_double and not escaped:
        return index + 1, not in_single, in_double, False, False, False
    if char == '"' and not in_single and not escaped:
        return index + 1, in_single, not in_double, False, False, False
    if not in_single and not in_double and line.startswith("<#", index):
        output[index : index + 2] = "  "
        return index + 2, in_single, in_double, False, True, False
    if char == "#" and not in_single and not in_double:
        return index, in_single, in_double, False, False, True
    return index + 1, in_single, in_double, False, False, False


def _line_without_block_comments(line: str, in_block: bool) -> tuple[str, bool]:
    output = list(line)
    in_single = False
    in_double = False
    escaped = False
    index = 0
    while index < len(line):
        if in_block:
            index, in_block = _mask_block_comment(output, line, index)
            if in_block:
                break
            continue
        index, in_single, in_double, escaped, opens_block, stops = _scan_code_char(
            output,
            line,
            index,
            in_single=in_single,
            in_double=in_double,
            escaped=escaped,
        )
        in_block = in_block or opens_block
        if stops:
            break
    return "".join(output), in_block


def _powershell_here_string_terminator(line: str, structural: str) -> str | None:
    for index, char in enumerate(structural):
        if char != "@" or index + 1 >= len(line):
            continue
        quote = line[index + 1]
        if quote in {"'", '"'} and not line[index + 2 :].strip():
            return f"{quote}@"
    return None


def powershell_without_here_string_literals(text: str) -> str:
    """Remove PowerShell here-strings and block comments from executable text."""
    reachable: list[str] = []
    here_string_terminator: str | None = None
    in_block_comment = False
    for line in text.splitlines():
        if here_string_terminator is not None:
            if line == here_string_terminator:
                here_string_terminator = None
            continue
        cleaned, in_block_comment = _line_without_block_comments(
            line, in_block_comment
        )
        structural = _powershell_structure(cleaned)
        if terminator := _powershell_here_string_terminator(cleaned, structural):
            here_string_terminator = terminator
            continue
        if cleaned.strip():
            reachable.append(cleaned)
    return "\n".join(reachable)


def powershell_statement_depths(text: str) -> list[int]:
    """Return brace depth for each executable PowerShell line.

    A leading closing brace belongs to the parent statement, so ``}`` and
    ``} else {`` are reported at the parent depth. Strings, comments, and
    here-strings are masked before braces are counted.
    """

    depths: list[int] = []
    depth = 0
    for line in powershell_without_here_string_literals(text).splitlines():
        structural = _powershell_structure(line).strip()
        leading_closes = len(structural) - len(structural.lstrip("}"))
        depth = max(0, depth - leading_closes)
        depths.append(depth)
        remainder = structural[leading_closes:]
        depth = max(0, depth + remainder.count("{") - remainder.count("}"))
    return depths


def _powershell_skip_state(
    *, waiting_for_open: bool, depth: int, opens: int, closes: int
) -> tuple[bool, bool, int]:
    if waiting_for_open and not opens:
        return True, True, depth
    if waiting_for_open:
        depth = opens - closes
        return depth > 0, False, depth
    depth += opens - closes
    return depth > 0, False, depth


def _powershell_terminal_prefix(line: str, structural: str) -> tuple[str, str | None]:
    terminal = re.search(r"(?i)(^|[;&|])\s*(?:exit|return)\b", structural)
    if terminal is None:
        return line, None
    separator = terminal.group(1)
    cut = terminal.start(1) if separator else terminal.start()
    keyword = re.search(r"(?i)(?:exit|return)\b", structural[terminal.start() :])
    assert keyword is not None
    return line[:cut].rstrip(), keyword.group(0).lower()


def powershell_reachable_command_text(text: str) -> str:
    """Remove definitions, deferred scriptblocks, literals, and dead PowerShell."""
    if not powershell_ast_propagates_failure(text):
        return ""
    reachable: list[str] = []
    skipping = False
    waiting_for_open = False
    depth = 0
    for line in powershell_without_here_string_literals(text).splitlines():
        structural = _powershell_structure(line)
        opens = structural.count("{")
        closes = structural.count("}")
        if skipping:
            skipping, waiting_for_open, depth = _powershell_skip_state(
                waiting_for_open=waiting_for_open,
                depth=depth,
                opens=opens,
                closes=closes,
            )
            continue
        if is_native_failure_propagation_guard(line):
            reachable.append(line)
            continue
        unreachable = any(
            pattern.match(structural.strip()) is not None
            for pattern in POWERSHELL_UNREACHABLE_STARTS
        ) or any(
            pattern.search(structural) is not None
            for pattern in POWERSHELL_UNREACHABLE_SCRIPTBLOCKS
        )
        if not unreachable:
            prefix, terminal = _powershell_terminal_prefix(line, structural)
            if prefix:
                reachable.append(prefix)
            if terminal is not None:
                reachable.append(terminal)
                break
            continue
        waiting_for_open = not bool(opens)
        depth = opens - closes
        skipping = waiting_for_open or depth > 0
    return "\n".join(reachable)


def looks_like_powershell(*, shell: str, command: str) -> bool:
    shell_parts = shell.split(maxsplit=1)
    shell_name = shell_parts[0].lower() if shell_parts else ""
    return shell_name in POWERSHELL_SHELLS or re.search(
        r"(?im)^\s*(?:function\s+|if\s*\(\s*\$false|while\s*\(\s*\$false|try\s*\{|\$[A-Za-z_])",
        command,
    ) is not None


def is_native_failure_propagation_guard(line: str) -> bool:
    return (
        re.fullmatch(
            r"""(?ix)
            \s*if\s*\(\s*\$LASTEXITCODE\s+-ne\s+0\s*\)\s*
            \{\s*(?:throw\b.+|exit\s+\$LASTEXITCODE\s*)\}\s*
            """,
            line,
        )
        is not None
    )
