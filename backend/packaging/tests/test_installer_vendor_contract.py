from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import uuid
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.packaging_resource("windows_fs")

PACKAGING = Path(__file__).resolve().parents[1]
PG_BUNDLE_SCRIPT = PACKAGING / "build_pg_bundle.ps1"
VENDOR_ROOT = PACKAGING / "vendor"


def _write_toolchain_config(path: Path, archive: Path) -> None:
    config = {
        "installer_vendor_sources": {
            "postgresql": {
                "version": "17.10-1",
                "archive_name": archive.name,
                "url": "https://example.test/postgresql.zip",
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "payload_file_count": 1,
                "payload_fingerprint": "0" * 64,
            }
        }
    }
    path.write_text(json.dumps(config), encoding="utf-8")


def _run_pg_bundle(archive: Path, config: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PG_BUNDLE_SCRIPT),
            "-Zip",
            str(archive),
            "-OutDir",
            str(output),
            "-ToolchainConfigPath",
            str(config),
            "-Force",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="Windows only")
def test_pg_archive_rejects_unsafe_entries_before_payload_selection(tmp_path: Path) -> None:
    cases: list[tuple[str, list[zipfile.ZipInfo | str], str]] = [
        ("dot-segment", ["../outside.txt"], "dot-segment"),
        ("absolute", ["C:/outside.txt"], "dot-segment"),
        (
            "case-duplicate",
            ["pgsql/share/Locale.txt", "pgsql/share/locale.txt"],
            "大小写冲突或重复 entry",
        ),
    ]
    symlink = zipfile.ZipInfo("discarded/link")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    cases.append(("symlink", [symlink], "symlink/reparse/特殊 entry"))
    reparse = zipfile.ZipInfo("discarded/reparse")
    reparse.create_system = 0
    reparse.external_attr = 0x0400
    cases.append(("reparse", [reparse], "symlink/reparse/特殊 entry"))

    VENDOR_ROOT.mkdir(exist_ok=True)
    for case_name, entries, expected_error in cases:
        archive = tmp_path / f"{case_name}.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for entry in entries:
                bundle.writestr(entry, b"payload")
        config = tmp_path / f"{case_name}.json"
        _write_toolchain_config(config, archive)
        output = VENDOR_ROOT / f".unsafe-probe-{uuid.uuid4().hex}"
        try:
            result = _run_pg_bundle(archive, config, output)
            combined = result.stdout + result.stderr
            assert result.returncode != 0, f"{case_name} archive was accepted: {combined}"
            assert expected_error in combined
            assert not output.exists()
        finally:
            if output.exists():
                shutil.rmtree(output)
