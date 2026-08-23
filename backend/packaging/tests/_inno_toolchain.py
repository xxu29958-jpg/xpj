from __future__ import annotations

import functools
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

PACKAGING = Path(__file__).resolve().parents[1]
BACKEND = PACKAGING.parent
TOOLCHAIN_CONTRACT = PACKAGING / "windows-build-toolchain.json"
PINNED_INNO_ROOT = BACKEND / "build" / "windows-toolchain" / "inno"


@functools.cache
def pinned_inno_compiler() -> Path:
    contract = json.loads(TOOLCHAIN_CONTRACT.read_text(encoding="utf-8"))
    source = contract["build_tool_sources"]["inno_setup"]
    version = source["version"]
    assert isinstance(version, str) and re.fullmatch(r"[1-9]\d*\.\d+\.\d+", version), (
        "pinned Inno Setup version must be an explicit three-part release"
    )

    relative_path = Path(source["compiler_relative_path"])
    assert not relative_path.is_absolute() and relative_path.parts == (relative_path.name,), (
        "pinned Inno compiler path must name one file"
    )
    compiler = PINNED_INNO_ROOT / relative_path
    assert compiler.is_file(), f"pinned Inno Setup {version} compiler is missing: {compiler}"

    expected_sha256 = source["compiler_sha256"]
    assert isinstance(expected_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", expected_sha256), (
        "pinned Inno compiler SHA-256 is malformed"
    )
    with compiler.open("rb") as stream:
        actual_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    assert actual_sha256 == expected_sha256, (
        f"pinned Inno compiler SHA-256 drifted: expected={expected_sha256} actual={actual_sha256}"
    )

    with tempfile.TemporaryDirectory(prefix="ticketbox-inno-version-") as temp_name:
        temp_root = Path(temp_name)
        probe = temp_root / "version-probe.iss"
        probe.write_text(
            "\n".join(
                (
                    "[Setup]",
                    "AppName=TicketboxCompilerProbe",
                    "AppVersion=1.0.0",
                    r"DefaultDirName={tmp}\TicketboxCompilerProbe",
                    "Uninstallable=no",
                    "OutputBaseFilename=version-probe",
                    "",
                )
            ),
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [compiler, probe],
            cwd=temp_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    match = re.search(r"(?m)^Compiler engine version:\s+Inno Setup\s+(\d+\.\d+\.\d+)\s*$", output)
    assert match is not None, "could not read pinned Inno compiler engine version"
    assert match.group(1) == version, f"pinned Inno version drifted: expected={version} actual={match.group(1)}"
    return compiler
