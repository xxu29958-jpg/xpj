"""Required non-Gradle commands for the CI gap audit."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ci_gap_shell import shell_tokens


@dataclass(frozen=True)
class RequiredCommand:
    label: str
    pattern: re.Pattern[str]
    matcher: Callable[[str], bool] | None = None

    def matches(self, command: str) -> bool:
        if self.matcher is not None:
            return self.matcher(command)
        return self.pattern.search(command) is not None


@dataclass(frozen=True)
class RequiredAction:
    label: str
    uses: str
    inputs: tuple[tuple[str, str], ...]

    def matches(self, uses: str, inputs: tuple[tuple[str, str], ...]) -> bool:
        supplied = dict(inputs)
        return uses == self.uses and all(
            supplied.get(key) == value for key, value in self.inputs
        )


_PYTHON_COMMAND = r"(?:python(?:\.exe)?|[^\s]+[\\/]python(?:\.exe)?)"
_PYTHON_PREFIX = rf"(?i)^\s*(?:&\s+)?{_PYTHON_COMMAND}\s+"
_RUFF_PREFIX = r"(?i)^\s*(?:&\s+)?(?:ruff(?:\.exe)?|[^\s]+[\\/]ruff(?:\.exe)?)\s+"
_PYTEST_LINE = rf"(?m)^\s*{_PYTHON_COMMAND}\s+-m\s+pytest\s+"
_BACKEND_TARGETS = r"app\s+scripts\s+tests\s+packaging[\\/]+tests"


def _command_tokens(command: str) -> tuple[str, ...]:
    tokens = shell_tokens(command)
    return tokens[1:] if tokens and tokens[0] == "&" else tokens


def _postgres_lane_invocation(command: str) -> tuple[str, int] | None:
    tokens = _command_tokens(command)
    if len(tokens) != 7:
        return None
    executable = tokens[0].replace("\\", "/").lower().rsplit("/", 1)[-1]
    if executable not in {"python", "python.exe"}:
        return None
    if tokens[1:3] != ("-m", "scripts.run_postgres_pytest_lane"):
        return None
    if tokens[3] != "--lane" or tokens[5] != "--workers":
        return None
    try:
        return tokens[4], int(tokens[6])
    except ValueError:
        return None


def _matches_ordinary_pytest(command: str) -> bool:
    invocation = _postgres_lane_invocation(command)
    return invocation is not None and invocation[0] == "ordinary" and 1 <= invocation[1] <= 4


def _matches_real_db_pytest(command: str) -> bool:
    return _postgres_lane_invocation(command) == ("real-db", 1)


def _matches_ci_contract_runner(command: str) -> bool:
    tokens = _command_tokens(command)
    if len(tokens) != 2:
        return False
    executable = tokens[0].replace("\\", "/").lower().rsplit("/", 1)[-1]
    script = tokens[1].replace("\\", "/").lower().removeprefix("./")
    return executable in {"python", "python.exe"} and script == (
        "scripts/run_ci_contract_tests.py"
    )


def _powershell_file_invocation(
    command: str,
    *,
    executables: set[str],
) -> tuple[str, tuple[str, ...]] | None:
    tokens = _command_tokens(command)
    if not tokens:
        return None
    executable = tokens[0].replace("\\", "/").lower().rsplit("/", 1)[-1]
    if executable not in executables:
        return None
    lowered = tuple(token.lower() for token in tokens)
    try:
        file_index = lowered.index("-file")
    except ValueError:
        return None
    if file_index + 1 >= len(tokens) or any(
        mode in {"-command", "-c", "-encodedcommand", "-enc", "-e"}
        for mode in lowered[1:file_index]
    ):
        return None
    script = tokens[file_index + 1].replace("\\", "/").lower().removeprefix("./")
    return script, lowered[file_index + 2 :]


def _matches_installer_source_preflight(command: str, *, executables: set[str]) -> bool:
    invocation = _powershell_file_invocation(command, executables=executables)
    if invocation is None:
        return False
    script, arguments = invocation
    return script == "packaging/build_inno_installer.ps1" and (
        "-checksourceinputsonly" in arguments
    )


def _matches_windows_powershell_installer_source_preflight(command: str) -> bool:
    return _matches_installer_source_preflight(
        command,
        executables={"powershell", "powershell.exe"},
    )


def _matches_pwsh_installer_source_preflight(command: str) -> bool:
    return _matches_installer_source_preflight(
        command,
        executables={"pwsh", "pwsh.exe"},
    )


def _matches_frozen_backend_build(command: str) -> bool:
    invocation = _powershell_file_invocation(
        command,
        executables={"powershell", "powershell.exe", "pwsh", "pwsh.exe"},
    )
    if invocation is None:
        return False
    script, arguments = invocation
    return script == "scripts/build_backend_exe.ps1" and "-clean" in arguments


def _matches_authoritative_inno_build(command: str) -> bool:
    invocation = _powershell_file_invocation(
        command,
        executables={"powershell", "powershell.exe", "pwsh", "pwsh.exe"},
    )
    if invocation is None:
        return False
    script, arguments = invocation
    return script == "packaging/build_inno_installer.ps1" and arguments == (
        "-installerhashoutputfile",
        "$env:github_output",
    )


def _matches_installer_publish_verification(command: str) -> bool:
    invocation = _powershell_file_invocation(
        command,
        executables={"powershell", "powershell.exe", "pwsh", "pwsh.exe"},
    )
    if invocation is None:
        return False
    script, arguments = invocation
    return script == "packaging/build_inno_installer.ps1" and arguments == (
        "-verifyonly",
        "-expectedinstallersha256",
        "$env:installer_expected_sha256",
    )


def _matches_uploaded_installer_verification(command: str) -> bool:
    invocation = _powershell_file_invocation(
        command,
        executables={"powershell", "powershell.exe", "pwsh", "pwsh.exe"},
    )
    if invocation is None:
        return False
    script, arguments = invocation
    return script == "packaging/build_inno_installer.ps1" and arguments == (
        "-verifyonly",
        "-expectedinstallersha256",
        "$env:installer_expected_sha256",
        "-verifypublishdirectory",
        "$env:installer_verify_download_path",
    )


REQUIRED_CI_INVOCATIONS = (
    RequiredCommand(
        "release audit aggregator",
        re.compile(_PYTHON_PREFIX + r"scripts[\\/]+release_audit\.py\b"),
    ),
    RequiredCommand(
        "pytest ordinary business lane",
        re.compile(_PYTHON_PREFIX + r"-m\s+scripts\.run_postgres_pytest_lane\b"),
        matcher=_matches_ordinary_pytest,
    ),
    RequiredCommand(
        "pytest real-db serial lane",
        re.compile(_PYTHON_PREFIX + r"-m\s+scripts\.run_postgres_pytest_lane\b"),
        matcher=_matches_real_db_pytest,
    ),
    RequiredCommand(
        "pytest installer safety lane",
        re.compile(
            _PYTEST_LINE
            + r"-q\s+packaging[\\/]+tests\s+-p\s+no:cacheprovider\s*$"
        ),
    ),
    RequiredCommand(
        "installer source preflight (Windows PowerShell 5.1)",
        re.compile(
            r"(?i)^\s*(?:&\s+)?powershell(?:\.exe)?\b[^\r\n]*\s-File\s+"
            r"(?:\.[\\/])?packaging[\\/]+build_inno_installer\.ps1\b"
            r"[^\r\n]*\s-CheckSourceInputsOnly\b"
        ),
        matcher=_matches_windows_powershell_installer_source_preflight,
    ),
    RequiredCommand(
        "installer source preflight (PowerShell 7)",
        re.compile(
            r"(?i)^\s*(?:&\s+)?pwsh(?:\.exe)?\b[^\r\n]*\s-File\s+"
            r"(?:\.[\\/])?packaging[\\/]+build_inno_installer\.ps1\b"
            r"[^\r\n]*\s-CheckSourceInputsOnly\b"
        ),
        matcher=_matches_pwsh_installer_source_preflight,
    ),
    RequiredCommand(
        "frozen backend locked release build",
        re.compile(
            r"(?i)^\s*(?:&\s+)?(?:powershell|pwsh)(?:\.exe)?\b[^\r\n]*\s-File\s+"
            r"(?:\.[\\/])?scripts[\\/]+build_backend_exe\.ps1\b"
            r"[^\r\n]*\s-Clean\b"
        ),
        matcher=_matches_frozen_backend_build,
    ),
    RequiredCommand(
        "end-to-end smoke",
        re.compile(_PYTHON_PREFIX + r"scripts[\\/]+smoke_test\.py\b"),
    ),
    RequiredCommand(
        "backup/restore drill",
        re.compile(_PYTHON_PREFIX + r"scripts[\\/]+postgres_backup_drill\.py\b"),
    ),
    RequiredCommand(
        "API contract check",
        re.compile(_PYTHON_PREFIX + r"scripts[\\/]+check_api_contract\.py\b"),
    ),
    RequiredCommand(
        "backend ruff lint",
        re.compile(_RUFF_PREFIX + rf"check\s+{_BACKEND_TARGETS}\b"),
    ),
    RequiredCommand(
        "backend compileall",
        re.compile(_PYTHON_PREFIX + rf"-m\s+compileall\s+{_BACKEND_TARGETS}\b"),
    ),
    RequiredCommand(
        "desktop compileall",
        re.compile(_PYTHON_PREFIX + r"-m\s+compileall\s+backend_manager\s+tests\b"),
    ),
    RequiredCommand(
        "desktop ruff lint",
        re.compile(_RUFF_PREFIX + r"check\s+backend_manager\s+tests\b"),
    ),
    RequiredCommand(
        "desktop pytest",
        re.compile(_PYTHON_PREFIX + r"-m\s+pytest\s+-q\s*$", re.MULTILINE),
    ),
)

_REQUIRED_INNO_BUILD_INVOCATIONS = (
    RequiredCommand(
        "authoritative Inno installer compile",
        re.compile(
            r"(?i)^\s*(?:&\s+)?(?:powershell|pwsh)(?:\.exe)?\b[^\r\n]*\s-File\s+"
            r"(?:\.[\\/])?packaging[\\/]+build_inno_installer\.ps1\b"
            r"[^\r\n]*\s-InstallerHashOutputFile\s+[^\r\n]*GITHUB_OUTPUT\s*$"
        ),
        matcher=_matches_authoritative_inno_build,
    ),
    RequiredCommand(
        "atomic installer publish-unit verification",
        re.compile(
            r"(?i)^\s*(?:&\s+)?(?:powershell|pwsh)(?:\.exe)?\b[^\r\n]*\s-File\s+"
            r"(?:\.[\\/])?packaging[\\/]+build_inno_installer\.ps1\b"
            r"[^\r\n]*\s-VerifyOnly\b"
        ),
        matcher=_matches_installer_publish_verification,
    ),
)

REQUIRED_CI_INVOCATIONS_BY_PLATFORM = {
    "GitHub": _REQUIRED_INNO_BUILD_INVOCATIONS,
    "Gitea": _REQUIRED_INNO_BUILD_INVOCATIONS,
}

REQUIRED_CI_GATES_BY_PLATFORM = {
    "GitHub": (
        RequiredCommand(
            "CI orchestration contract runner",
            re.compile(_PYTHON_PREFIX + r"scripts[\\/]+run_ci_contract_tests\.py\b"),
            matcher=_matches_ci_contract_runner,
        ),
    ),
    "Gitea": (),
}

REQUIRED_INSTALLER_POST_UPLOAD_INVOCATION_BY_PLATFORM = {
    platform: RequiredCommand(
        "uploaded installer byte verification",
        re.compile(
            r"(?i)^\s*(?:&\s+)?(?:powershell|pwsh)(?:\.exe)?\b[^\r\n]*\s-File\s+"
            r"(?:\.[\\/])?packaging[\\/]+build_inno_installer\.ps1\b"
            r"[^\r\n]*\s-VerifyPublishDirectory\b"
        ),
        matcher=_matches_uploaded_installer_verification,
    )
    for platform in ("GitHub", "Gitea")
}

_INSTALLER_UPLOAD_INPUTS = (
    ("name", "ticketbox-windows-installer"),
    ("path", "${{ env.INSTALLER_PUBLISH_PATH }}"),
    ("if-no-files-found", "error"),
)
_INSTALLER_DOWNLOAD_INPUTS = (
    ("name", "ticketbox-windows-installer"),
    ("path", "${{ env.INSTALLER_VERIFY_DOWNLOAD_PATH }}"),
)
REQUIRED_CI_ACTIONS_BY_PLATFORM = {
    "GitHub": (
        RequiredAction(
            "atomic installer publish-unit artifact upload",
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            _INSTALLER_UPLOAD_INPUTS,
        ),
        RequiredAction(
            "uploaded installer publish-unit download",
            "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
            _INSTALLER_DOWNLOAD_INPUTS,
        ),
    ),
    "Gitea": (
        RequiredAction(
            "atomic installer publish-unit artifact upload",
            "actions/upload-artifact@a8a3f3ad30e3422c9c7b888a15615d19a852ae32",
            _INSTALLER_UPLOAD_INPUTS,
        ),
        RequiredAction(
            "uploaded installer publish-unit download",
            "actions/download-artifact@9bc31d5ccc31df68ecc42ccf4149144866c47d8a",
            _INSTALLER_DOWNLOAD_INPUTS,
        ),
    ),
}
