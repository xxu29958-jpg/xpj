from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._infra.android_nvd_scripts import (
    install_nvd_scripts,
    prepare_payload_manifest,
    read_calls,
    run_nvd_script,
    write_fake_gradlew,
)

pytestmark = pytest.mark.parallel_safe


@pytest.mark.parametrize(
    (
        "api_key",
        "update_rc",
        "analyze_rc",
        "report_mode",
        "payload_mode",
        "existing_payload",
        "expected_rc",
        "expected_calls",
    ),
    [
        ("", 0, 0, "valid", "valid", False, 78, []),
        (
            "configured",
            0,
            0,
            "valid",
            "valid",
            False,
            0,
            ["update", "validate"],
        ),
        (
            "configured",
            0,
            0,
            "vulnerable",
            "valid",
            False,
            0,
            ["update", "validate"],
        ),
        (
            "configured",
            0,
            0,
            "no-app",
            "valid",
            False,
            1,
            ["update", "validate"],
        ),
        (
            "configured",
            0,
            0,
            "not-refreshed",
            "preserve",
            True,
            1,
            ["update", "validate"],
        ),
        ("configured", 1, 0, "valid", "valid", False, 1, ["update"]),
        (
            "configured",
            0,
            1,
            "valid",
            "valid",
            False,
            1,
            ["update", "validate"],
        ),
        (
            "configured",
            0,
            0,
            "missing",
            "valid",
            False,
            1,
            ["update", "validate"],
        ),
    ],
)
def test_refresh_publishes_manifest_only_after_complete_payload_proof(
    tmp_path: Path,
    api_key: str,
    update_rc: int,
    analyze_rc: int,
    report_mode: str,
    payload_mode: str,
    existing_payload: bool,
    expected_rc: int,
    expected_calls: list[str],
) -> None:
    write_fake_gradlew(tmp_path)
    install_nvd_scripts(tmp_path, "refresh_dependency_check_nvd.sh")
    manifest = (
        tmp_path
        / ".dependency-check-data"
        / "xpj-nvd-payload-manifest.json"
    )
    if existing_payload:
        prepare_payload_manifest(tmp_path, mode="valid")
    result = run_nvd_script(
        tmp_path,
        "refresh_dependency_check_nvd.sh",
        environment={
            "NVD_API_KEY": api_key,
            "FAKE_UPDATE_RC": str(update_rc),
            "FAKE_ANALYZE_RC": str(analyze_rc),
            "FAKE_REPORT_MODE": report_mode,
            "FAKE_PAYLOAD_MODE": payload_mode,
        },
    )
    assert result.returncode == expected_rc, result.stdout + result.stderr
    assert read_calls(tmp_path) == expected_calls
    if expected_rc == 0:
        assert manifest.is_file()
        assert "NVD_PAYLOAD_MANIFEST_CREATED" in result.stdout
    else:
        assert not manifest.exists()


@pytest.mark.parametrize(
    (
        "manifest_mode",
        "api_key",
        "analyze_rc",
        "report_mode",
        "expected_rc",
        "expected_calls",
    ),
    [
        ("valid", "", 0, "valid", 0, ["validate"]),
        ("valid", "", 0, "vulnerable", 0, ["validate"]),
        ("valid", "must-not-enter", 0, "valid", 78, []),
        ("missing", "", 0, "valid", 1, []),
        ("expired", "", 0, "valid", 1, []),
        ("future", "", 0, "valid", 1, []),
        ("tampered", "", 0, "valid", 1, []),
        ("bad-digest", "", 0, "valid", 1, []),
        ("malformed", "", 0, "valid", 1, []),
        ("valid", "", 1, "valid", 1, ["validate"]),
        ("valid", "", 0, "missing", 1, ["validate"]),
        ("valid", "", 0, "no-app", 1, ["validate"]),
    ],
)
def test_certifier_rejects_unproven_payload_states(
    tmp_path: Path,
    manifest_mode: str,
    api_key: str,
    analyze_rc: int,
    report_mode: str,
    expected_rc: int,
    expected_calls: list[str],
) -> None:
    write_fake_gradlew(tmp_path)
    install_nvd_scripts(tmp_path, "certify_dependency_check_nvd_payload.sh")
    prepare_payload_manifest(tmp_path, mode=manifest_mode)
    result = run_nvd_script(
        tmp_path,
        "certify_dependency_check_nvd_payload.sh",
        environment={
            "NVD_API_KEY": api_key,
            "FAKE_ANALYZE_RC": str(analyze_rc),
            "FAKE_REPORT_MODE": report_mode,
        },
    )
    assert result.returncode == expected_rc, result.stdout + result.stderr
    assert read_calls(tmp_path) == expected_calls


def test_report_contract_rejects_forged_or_wrong_scope_documents(
    tmp_path: Path,
) -> None:
    write_fake_gradlew(tmp_path)
    install_nvd_scripts(tmp_path)
    report_script = (
        tmp_path / "scripts" / "verify_dependency_check_report.py"
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key != "NVD_API_KEY"
    }
    accepted = subprocess.run(
        [
            sys.executable,
            str(report_script),
            str(tmp_path / "fake-reports" / "valid.json"),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    for report_name in (
        "minimal",
        "wrong-schema",
        "wrong-engine",
        "bad-references",
        "foreign-app",
        "partial-app",
        "analysis-exception",
        "no-app",
        "stale-nvd",
    ):
        rejected = subprocess.run(
            [
                sys.executable,
                str(report_script),
                str(tmp_path / "fake-reports" / f"{report_name}.json"),
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
        )
        assert rejected.returncode != 0, report_name
