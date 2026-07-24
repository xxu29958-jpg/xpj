"""Run Android dependency audits from trusted or freshly downloaded NVD data."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tomllib
import urllib.parse
from collections.abc import Callable
from pathlib import Path


class AuditError(RuntimeError):
    """The dependency audit could not prove a safe result."""


class ArtifactError(AuditError):
    """The downloaded artifact does not contain a usable NVD database."""


TaskRunner = Callable[[str, Path], int]
SCAN_TASK = "dependencyCheckAggregate"
UPDATE_TIMEOUT_SECONDS = 22 * 60
SCAN_TIMEOUT_SECONDS = 10 * 60
APP_DEPENDENCY_CATALOG_ALIAS = "retrofit"


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _create_owned_directory(
    path: Path,
    *,
    label: str,
    error_type: type[AuditError] = AuditError,
) -> None:
    if path.exists() or path.is_symlink():
        raise error_type(f"{label} must not already exist")
    try:
        path.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise error_type(f"{label} could not be created") from exc
    if path.is_symlink() or not path.is_dir():
        raise error_type(f"{label} is not an owned directory")


def _remove_owned_directory(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or not path.is_dir():
        raise AuditError("an owned NVD directory changed before cleanup")
    shutil.rmtree(path)


def _require_database_payload(database: Path) -> None:
    if database.is_symlink() or not database.is_dir():
        raise ArtifactError("no trusted NVD artifact is available")
    entries = list(database.rglob("*"))
    if any(entry.is_symlink() for entry in entries):
        raise ArtifactError("the NVD artifact contains a symbolic link")
    payloads = [
        path
        for path in entries
        if path.is_file() and path.name == "odc.mv.db" and path.stat().st_size > 0
    ]
    if len(payloads) != 1:
        raise ArtifactError("the NVD artifact must contain one database payload")


def _catalog_library_coordinate(
    catalog: Path,
    alias: str,
) -> tuple[str, str, str]:
    try:
        with catalog.open("rb") as handle:
            payload = tomllib.load(handle)
        library = payload["libraries"][alias]
        module = library["module"]
        version_spec = library["version"]
        version = (
            version_spec
            if isinstance(version_spec, str)
            else payload["versions"][version_spec["ref"]]
        )
    except (KeyError, OSError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise AuditError("the Android dependency catalog anchor is invalid") from exc
    if (
        not isinstance(module, str)
        or module.count(":") != 1
        or not isinstance(version, str)
        or not version
    ):
        raise AuditError("the Android dependency catalog anchor is invalid")
    group, artifact = module.split(":", maxsplit=1)
    if not group or not artifact:
        raise AuditError("the Android dependency catalog anchor is invalid")
    return group, artifact, version


def _maven_package_coordinate(package_id: object) -> tuple[str, str, str] | None:
    if not isinstance(package_id, str) or not package_id.startswith("pkg:maven/"):
        return None
    coordinate = package_id.removeprefix("pkg:maven/")
    coordinate = coordinate.split("?", maxsplit=1)[0].split("#", maxsplit=1)[0]
    module, separator, version = coordinate.rpartition("@")
    parts = module.split("/")
    if separator != "@" or len(parts) != 2 or not version:
        return None
    group, artifact = (urllib.parse.unquote(part) for part in parts)
    return group, artifact, urllib.parse.unquote(version)


def _require_app_dependency_report(report: Path, catalog: Path) -> None:
    expected = _catalog_library_coordinate(catalog, APP_DEPENDENCY_CATALOG_ALIAS)
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AuditError("the aggregate dependency report is missing or invalid") from exc
    dependencies = payload.get("dependencies") if isinstance(payload, dict) else None
    if not isinstance(dependencies, list):
        raise AuditError("the aggregate dependency report has no dependency inventory")
    for dependency in dependencies:
        packages = dependency.get("packages") if isinstance(dependency, dict) else None
        if not isinstance(packages, list):
            continue
        if any(
            _maven_package_coordinate(package.get("id")) == expected
            for package in packages
            if isinstance(package, dict)
        ):
            return
    raise AuditError(
        "the aggregate dependency report did not include the Android app anchor"
    )


def _copy_database(source: Path, target: Path) -> None:
    _require_database_payload(source)
    _create_owned_directory(
        target,
        label="NVD scan directory",
        error_type=ArtifactError,
    )
    try:
        shutil.copytree(source, target, dirs_exist_ok=True)
    except OSError as exc:
        _remove_owned_directory(target)
        raise ArtifactError("the NVD artifact could not be copied") from exc


def _analyze_copy(trusted: Path, scan: Path, run_task: TaskRunner) -> None:
    _copy_database(trusted, scan)
    if run_task(SCAN_TASK, scan) != 0:
        raise AuditError("dependency analysis failed")


def _refresh_and_analyze(
    destination: Path,
    run_task: TaskRunner,
    *,
    seed: Path | None = None,
) -> None:
    if seed is None:
        _create_owned_directory(destination, label="NVD refresh directory")
    else:
        try:
            _copy_database(seed, destination)
        except ArtifactError:
            print("Previous trusted NVD artifact is unusable; rebuilding from empty data.")
            _create_owned_directory(destination, label="NVD refresh directory")
    try:
        if run_task("dependencyCheckUpdate", destination) != 0:
            raise AuditError("NVD update failed")
        _require_database_payload(destination)
        if run_task(SCAN_TASK, destination) != 0:
            raise AuditError("dependency analysis failed")
        _require_database_payload(destination)
    except (AuditError, OSError):
        _remove_owned_directory(destination)
        raise


def run_dependency_audit(
    *,
    trusted: Path,
    work: Path,
    artifact_present: bool,
    has_api_key: bool,
    run_task: TaskRunner,
) -> str:
    """Scan a trusted main artifact, or refresh isolated data for this run."""
    if not artifact_present and not has_api_key:
        raise AuditError("a trusted NVD artifact or NVD_API_KEY is required")
    _create_owned_directory(work, label="NVD audit work directory")
    if artifact_present:
        try:
            _analyze_copy(trusted, work / "scan", run_task)
        except ArtifactError:
            if not has_api_key:
                raise
            print("Trusted NVD artifact is unusable; refreshing isolated data.")
        else:
            return "trusted-artifact"
    if not has_api_key:
        raise AuditError("a trusted NVD artifact or NVD_API_KEY is required")
    _refresh_and_analyze(work / "candidate", run_task)
    return "live-refresh"


def produce_dependency_database(
    *,
    output: Path,
    seed: Path | None = None,
    run_task: TaskRunner,
) -> None:
    """Produce a validated database for upload by the trusted main workflow."""
    _refresh_and_analyze(output, run_task, seed=seed)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


def _drain_terminated_process(process: subprocess.Popen[str]) -> str:
    try:
        output, _ = process.communicate(timeout=30)
        return output
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            process.kill()
        try:
            output, _ = process.communicate(timeout=30)
            return output
        except subprocess.TimeoutExpired:
            return "\nGradle process output could not be drained after termination.\n"


def _run_gradle_factory(
    gradlew: Path,
    log_path: Path,
    *,
    fail_on_findings: bool = True,
) -> TaskRunner:
    def run_task(task: str, database: Path) -> int:
        command = [
            str(gradlew),
            "--no-daemon",
            "--max-workers=2",
            task,
            f"-PdependencyCheckDataDir={database}",
        ]
        timeout_seconds = (
            UPDATE_TIMEOUT_SECONDS
            if task == "dependencyCheckUpdate"
            else SCAN_TIMEOUT_SECONDS
        )
        if task == "dependencyCheckUpdate":
            command.append("-PdependencyCheckNvdValidForHours=0")
        else:
            command.append("-PdependencyCheckAutoUpdate=false")
            if not fail_on_findings:
                # OWASP documents 11 as the non-failing threshold because CVSS
                # scores are bounded by 10. Scanner/data errors still fail.
                command.append("-PdependencyCheckFailBuildOnCVSS=11")
        try:
            process = subprocess.Popen(
                command,
                cwd=gradlew.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=os.name != "nt",
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
            )
        except OSError as exc:
            output = f"{task} could not start: {exc}\n"
            print(output, end="")
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(output)
            return 127
        try:
            output, _ = process.communicate(timeout=timeout_seconds)
            return_code = process.returncode
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process)
            output = _drain_terminated_process(process)
            output += f"\n{task} timed out after {timeout_seconds} seconds\n"
            return_code = 124
        if return_code == 0 and task == SCAN_TASK:
            try:
                _require_app_dependency_report(
                    gradlew.parent / "build" / "reports" / "dependency-check-report.json",
                    gradlew.parent / "gradle" / "libs.versions.toml",
                )
            except AuditError as exc:
                output += f"\n{exc}\n"
                return_code = 2
        print(output, end="")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(output)
        return return_code

    return run_task


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise AuditError(f"invalid boolean value: {value!r}")
    return normalized == "true"


def _add_gradle_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gradlew", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan")
    _add_gradle_arguments(scan)
    scan.add_argument("--trusted-dir", type=Path, required=True)
    scan.add_argument("--work-dir", type=Path, required=True)
    scan.add_argument("--artifact-present", required=True)

    produce = commands.add_parser("produce")
    _add_gradle_arguments(produce)
    produce.add_argument("--output-dir", type=Path, required=True)
    produce.add_argument("--seed-dir", type=Path, required=True)
    produce.add_argument("--seed-present", required=True)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    gradlew = args.gradlew.resolve()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("", encoding="utf-8")
    run_task = _run_gradle_factory(
        gradlew,
        args.log,
        fail_on_findings=args.command != "produce",
    )
    try:
        if args.command == "produce":
            if not os.environ.get("NVD_API_KEY", "").strip():
                raise AuditError("NVD_API_KEY is required to produce the trusted artifact")
            seed_present = _parse_bool(args.seed_present)
            produce_dependency_database(
                output=_absolute_path(args.output_dir),
                seed=_absolute_path(args.seed_dir) if seed_present else None,
                run_task=run_task,
            )
            return 0

        trusted = _absolute_path(args.trusted_dir)
        work = _absolute_path(args.work_dir)
        trusted_real = trusted.resolve(strict=False)
        work_real = work.resolve(strict=False)
        if (
            trusted_real == work_real
            or trusted_real in work_real.parents
            or work_real in trusted_real.parents
        ):
            parser.error("trusted-dir and work-dir must be separate trees")
        mode = run_dependency_audit(
            trusted=trusted,
            work=work,
            artifact_present=_parse_bool(args.artifact_present),
            has_api_key=bool(os.environ.get("NVD_API_KEY", "").strip()),
            run_task=run_task,
        )
        print(f"Android dependency audit completed via {mode}.")
        return 0
    except (AuditError, OSError) as exc:
        print(f"Android dependency audit failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
