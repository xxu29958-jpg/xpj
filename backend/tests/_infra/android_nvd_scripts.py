from __future__ import annotations

import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DEPENDENCY_CHECK_VERSION = "12.1.0"
_REQUIRED_APP_REFERENCES = (
    "app:grayDebugRuntimeClasspath",
    "app:grayReleaseRuntimeClasspath",
    "app:internalDebugRuntimeClasspath",
    "app:internalReleaseRuntimeClasspath",
)
_VALID_APP_REFERENCE = _REQUIRED_APP_REFERENCES[0]


def bash_executable() -> str:
    candidates = [
        shutil.which("bash"),
        str(
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
            / "Git/bin/bash.exe"
        ),
    ]
    match = next(
        (
            candidate
            for candidate in candidates
            if candidate and Path(candidate).is_file()
        ),
        None,
    )
    if match is None:
        raise AssertionError("Bash is required to execute the NVD producer contract")
    return match


def _iso_timestamp(moment: datetime) -> str:
    return (
        moment.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _valid_report(*, project_reference: object = None) -> dict:
    now = datetime.now(UTC)
    references = (
        [*_REQUIRED_APP_REFERENCES, "app:grayDebugCompileClasspath"]
        if project_reference is None
        else (
            [project_reference]
            if isinstance(project_reference, str)
            else project_reference
        )
    )
    return {
        "reportSchema": "1.1",
        "scanInfo": {
            "engineVersion": _DEPENDENCY_CHECK_VERSION,
            "dataSource": [
                {
                    "name": "NVD API Last Checked",
                    "timestamp": _iso_timestamp(now),
                },
                {
                    "name": "NVD API Last Modified",
                    "timestamp": _iso_timestamp(now - timedelta(hours=1)),
                },
            ],
        },
        "projectInfo": {
            "name": "xpj",
            "reportDate": _iso_timestamp(now),
        },
        "dependencies": [
            {
                "isVirtual": True,
                "fileName": "androidx.core:core-ktx:1.16.0",
                "filePath": "androidx.core:core-ktx:1.16.0",
                "projectReferences": references,
                "evidenceCollected": {
                    "vendorEvidence": [],
                    "productEvidence": [],
                    "versionEvidence": [],
                },
            }
        ],
    }


def _fake_reports() -> dict[str, dict]:
    valid = _valid_report()
    vulnerable = deepcopy(valid)
    vulnerable["dependencies"][0]["vulnerabilities"] = [
        {"cvssv3": {"baseScore": 9.8}}
    ]
    no_app = _valid_report(
        project_reference="macrobenchmark:grayBenchmarkRuntimeClasspath"
    )
    foreign_app = _valid_report(
        project_reference="app:grayBenchmarkRuntimeClasspath"
    )
    partial_app = _valid_report(project_reference=_VALID_APP_REFERENCE)
    bad_references = _valid_report(project_reference={_VALID_APP_REFERENCE: True})
    wrong_schema = deepcopy(valid)
    wrong_schema["reportSchema"] = "0.0"
    wrong_engine = deepcopy(valid)
    wrong_engine["scanInfo"]["engineVersion"] = "99.0.0"
    stale_nvd = deepcopy(valid)
    stale_nvd["scanInfo"]["dataSource"][0]["timestamp"] = _iso_timestamp(
        datetime.now(UTC) - timedelta(hours=25)
    )
    not_refreshed = deepcopy(valid)
    not_refreshed["scanInfo"]["dataSource"][0]["timestamp"] = _iso_timestamp(
        datetime.now(UTC) - timedelta(minutes=1)
    )
    analysis_exception = deepcopy(valid)
    analysis_exception["scanInfo"]["analysisExceptions"] = [
        {"exception": {"message": "fake analyzer failure"}}
    ]
    return {
        "valid": valid,
        "vulnerable": vulnerable,
        "no-app": no_app,
        "foreign-app": foreign_app,
        "partial-app": partial_app,
        "bad-references": bad_references,
        "wrong-schema": wrong_schema,
        "wrong-engine": wrong_engine,
        "stale-nvd": stale_nvd,
        "not-refreshed": not_refreshed,
        "analysis-exception": analysis_exception,
        "minimal": {
            "dependencies": [
                {"projectReferences": [_VALID_APP_REFERENCE]}
            ]
        },
    }


def _write_fake_version_catalog(tmp_path: Path) -> None:
    catalog = tmp_path / "gradle" / "libs.versions.toml"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        "[plugins]\n"
        'owasp-dependency-check = { id = "org.owasp.dependencycheck", '
        f'version = "{_DEPENDENCY_CHECK_VERSION}" }}\n',
        encoding="utf-8",
        newline="\n",
    )


def write_fake_gradlew(tmp_path: Path) -> None:
    _write_fake_version_catalog(tmp_path)
    reports = tmp_path / "fake-reports"
    reports.mkdir()
    for name, report in _fake_reports().items():
        (reports / f"{name}.json").write_text(
            json.dumps(report, separators=(",", ":")),
            encoding="utf-8",
            newline="\n",
        )

    gradlew = tmp_path / "gradlew"
    gradlew.write_text(
        """#!/usr/bin/env bash
set -u
if [[ " $* " == *" dependencyCheckUpdate "* ]]; then
  if [[ " $* " != *" -PdependencyCheckNvdValidForHours=0 "* ]]; then
    echo "update did not force a fresh NVD check: $*" >&2
    exit 96
  fi
  if [[ " $* " == *" -PnvdApiKey="* ]]; then
    echo "NVD credential leaked into Gradle arguments" >&2
    exit 93
  fi
  if [ -z "${NVD_API_KEY:-}" ]; then
    echo "update did not receive its protected NVD credential" >&2
    exit 92
  fi
  echo update >> calls.log
  update_rc="${FAKE_UPDATE_RC:-0}"
  if [ "$update_rc" -eq 0 ] && [ "${FAKE_PAYLOAD_MODE:-valid}" = "valid" ]; then
    mkdir -p "${DEPENDENCY_CHECK_DATA_DIR:?}/11.0"
    printf 'fake-nvd-data\\n' > "${DEPENDENCY_CHECK_DATA_DIR}/11.0/odc.mv.db"
  fi
  exit "$update_rc"
fi
if [[ " $* " != *" dependencyCheckValidateNvd "* ]]; then
  echo "unexpected fake Gradle invocation: $*" >&2
  exit 97
fi
if [[ " $* " != *" -PdependencyCheckAutoUpdate=false "* ]]; then
  echo "validation did not disable updates: $*" >&2
  exit 98
fi
if [[ " $* " != *" -PdependencyCheckNvdValidForHours=0 "* ]]; then
  echo "validation did not bind the forced freshness contract: $*" >&2
  exit 95
fi
if [[ " $* " == *" -PdependencyCheckFailBuildOnCvss="* ]]; then
  echo "validation accepted a caller-controlled CVSS threshold" >&2
  exit 94
fi
if [ -n "${NVD_API_KEY:-}" ]; then
  echo "validation inherited the NVD credential" >&2
  exit 99
fi
echo validate >> calls.log
if [ "${FAKE_ANALYZE_RC:-0}" -ne 0 ]; then
  exit "${FAKE_ANALYZE_RC}"
fi
if [ "${FAKE_REPORT_MODE:-valid}" = "missing" ]; then
  exit 0
fi
mkdir -p build/reports
cp "fake-reports/${FAKE_REPORT_MODE:-valid}.json" \
  build/reports/dependency-check-report.json
""",
        encoding="utf-8",
        newline="\n",
    )
    gradlew.chmod(0o755)


def install_nvd_scripts(tmp_path: Path, *names: str) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    for name in (
        *names,
        "dependency_check_contract.py",
        "dependency_check_nvd_manifest.py",
        "verify_dependency_check_report.py",
    ):
        shutil.copyfile(_ROOT / "android" / "scripts" / name, scripts / name)
    contract_namespace = runpy.run_path(
        str(_ROOT / "android" / "scripts" / "dependency_check_contract.py")
    )
    for relative in contract_namespace["PRODUCER_CONTRACT_PATHS"]:
        source = _ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _install_python3_shim(tmp_path: Path) -> Path:
    binary_dir = tmp_path / ".test-bin"
    binary_dir.mkdir(exist_ok=True)
    python3 = binary_dir / "python3"
    python3.write_text(
        "#!/usr/bin/env bash\n"
        f"exec {shlex.quote(Path(sys.executable).as_posix())} \"$@\"\n",
        encoding="utf-8",
        newline="\n",
    )
    python3.chmod(0o755)
    return binary_dir


def run_nvd_script(
    tmp_path: Path,
    script_name: str,
    *,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    binary_dir = _install_python3_shim(tmp_path)
    return subprocess.run(
        [bash_executable(), (tmp_path / "scripts" / script_name).as_posix()],
        cwd=tmp_path,
        env={
            **os.environ,
            "DEPENDENCY_CHECK_DATA_DIR": ".dependency-check-data",
            "REPOSITORY_ROOT": str(tmp_path),
            "PATH": f"{binary_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "PYTHON_BIN": "true",
            **environment,
        },
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )


def prepare_payload_manifest(tmp_path: Path, *, mode: str) -> None:
    data_dir = tmp_path / ".dependency-check-data"
    payload = data_dir / "11.0" / "odc.mv.db"
    payload.parent.mkdir(parents=True)
    payload.write_text("fake-nvd-data\n", encoding="utf-8", newline="\n")
    manifest_script = (
        tmp_path / "scripts" / "dependency_check_nvd_manifest.py"
    )
    report = tmp_path / "fake-reports" / "valid.json"
    created = subprocess.run(
        [
            sys.executable,
            str(manifest_script),
            "create",
            str(data_dir),
            "--report",
            str(report),
            "--nvd-checked-after-epoch",
            str(int(time.time()) - 60),
        ],
        cwd=tmp_path,
        env={
            key: value
            for key, value in os.environ.items()
            if key != "NVD_API_KEY"
        }
        | {"REPOSITORY_ROOT": str(tmp_path)},
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    manifest_path = data_dir / "xpj-nvd-payload-manifest.json"
    if mode == "valid":
        return
    if mode == "missing":
        manifest_path.unlink()
        return
    if mode == "tampered":
        payload.write_text("tampered\n", encoding="utf-8", newline="\n")
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    now_epoch = int(time.time())
    if mode == "expired":
        manifest["refreshed_at_epoch"] = now_epoch - (25 * 60 * 60)
        manifest["expires_at_epoch"] = (
            manifest["refreshed_at_epoch"] + 24 * 60 * 60
        )
    elif mode == "future":
        manifest["refreshed_at_epoch"] = now_epoch + 10 * 60
        manifest["expires_at_epoch"] = (
            manifest["refreshed_at_epoch"] + 24 * 60 * 60
        )
    elif mode == "bad-digest":
        manifest["payload"]["sha256"] = "0" * 64
    elif mode == "malformed":
        manifest_path.write_text("{", encoding="utf-8", newline="\n")
        return
    else:
        raise AssertionError(f"unknown manifest mode: {mode}")
    manifest_path.write_text(
        json.dumps(manifest, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )


def read_calls(tmp_path: Path) -> list[str]:
    calls_path = tmp_path / "calls.log"
    return (
        calls_path.read_text(encoding="utf-8").splitlines()
        if calls_path.is_file()
        else []
    )
