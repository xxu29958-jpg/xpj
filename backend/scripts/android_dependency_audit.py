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
from collections.abc import Callable
from pathlib import Path

import nvd_artifact_contract as nvd_contract

ARTIFACT_MANIFEST_NAME = nvd_contract.ARTIFACT_MANIFEST_NAME
ArtifactError = nvd_contract.ArtifactError
AuditError = nvd_contract.AuditError
_producer_contract_digest = nvd_contract.producer_contract_digest
_require_artifact_payload = nvd_contract.require_artifact_payload
_require_database_payload = nvd_contract.require_database_payload
_write_artifact_manifest = nvd_contract.write_artifact_manifest


TaskRunner = Callable[[str, Path], int]
SCAN_TASK = "dependencyCheckAggregate"
UPDATE_TIMEOUT_SECONDS = 22 * 60
SCAN_TIMEOUT_SECONDS = 10 * 60
DEPENDENCY_CHECK_PLUGIN_ALIAS = "owasp-dependency-check"
# Keep reusable database compatibility separate from producer lineage. Binding the
# artifact name to current PR inputs would require main to publish it before merge.
DEPENDENCY_CHECK_ARTIFACT_PREFIX = "ticketbox-nvd-database-compat"


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


def _catalog_plugin_version(catalog: Path, alias: str) -> str:
    try:
        with catalog.open("rb") as handle:
            payload = tomllib.load(handle)
        plugin = payload["plugins"][alias]
        version_spec = plugin["version"]
        version = (
            version_spec
            if isinstance(version_spec, str)
            else payload["versions"][version_spec["ref"]]
        )
    except (KeyError, OSError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise AuditError("the Dependency-Check plugin version is invalid") from exc
    if not isinstance(version, str) or not version or any(
        character not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._-"
        for character in version
    ):
        raise AuditError("the Dependency-Check plugin version is invalid")
    return version


def _dependency_artifact_metadata(
    catalog: Path,
    *,
    repository_root: Path,
    contract: Path,
) -> dict[str, str]:
    version = _catalog_plugin_version(catalog, DEPENDENCY_CHECK_PLUGIN_ALIAS)
    contract_digest = _producer_contract_digest(repository_root, contract)
    return {
        "version": version,
        "contract_digest": contract_digest,
        "database_compatibility": str(
            nvd_contract.NVD_DATABASE_COMPATIBILITY_VERSION
        ),
        "artifact": (
            f"{DEPENDENCY_CHECK_ARTIFACT_PREFIX}"
            f"{nvd_contract.NVD_DATABASE_COMPATIBILITY_VERSION}"
        ),
    }


def _project_references(payload: object, *, label: str) -> set[str]:
    if not isinstance(payload, dict):
        raise AuditError(f"the {label} is not an object")
    references = payload.get("projectReferences")
    if (
        not isinstance(references, list)
        or not references
        or any(not isinstance(reference, str) or not reference for reference in references)
        or len(set(references)) != len(references)
    ):
        raise AuditError(f"the {label} has invalid project references")
    return set(references)


def _require_app_dependency_report(report: Path, scope_contract: Path) -> None:
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
        expected_payload = json.loads(scope_contract.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AuditError("the aggregate dependency report contract is missing or invalid") from exc
    expected = _project_references(expected_payload, label="Gradle scan scope contract")
    dependencies = payload.get("dependencies") if isinstance(payload, dict) else None
    if not isinstance(dependencies, list):
        raise AuditError("the aggregate dependency report has no dependency inventory")
    observed: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        references = dependency.get("projectReferences")
        if references is None:
            continue
        if not isinstance(references, list) or any(
            not isinstance(reference, str) or not reference for reference in references
        ):
            raise AuditError("the aggregate dependency report has invalid project references")
        observed.update(references)
    if observed != expected:
        raise AuditError(
            "the aggregate dependency report did not cover the exact Gradle scan scope"
        )


def _copy_database(
    source: Path,
    target: Path,
    *,
    plugin_version: str | None = None,
    contract_digest: str | None = None,
) -> None:
    _require_artifact_payload(
        source,
        plugin_version=plugin_version,
        contract_digest=contract_digest,
    )
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


def _analyze_copy(
    trusted: Path,
    scan: Path,
    run_task: TaskRunner,
) -> None:
    _copy_database(trusted, scan)
    if run_task(SCAN_TASK, scan) != 0:
        raise AuditError("dependency analysis failed")


def _refresh_and_analyze(
    destination: Path,
    run_task: TaskRunner,
    *,
    plugin_version: str,
    contract_digest: str,
    seed: Path | None = None,
) -> None:
    if seed is None:
        _create_owned_directory(destination, label="NVD refresh directory")
    else:
        try:
            _copy_database(seed, destination, plugin_version=plugin_version)
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
        _write_artifact_manifest(
            destination,
            plugin_version=plugin_version,
            contract_digest=contract_digest,
        )
    except (AuditError, OSError):
        _remove_owned_directory(destination)
        raise


def run_dependency_audit(
    *,
    trusted: Path,
    work: Path,
    artifact_present: bool,
    run_task: TaskRunner,
) -> str:
    """Scan an immutable artifact produced by the trusted main workflow."""
    if not artifact_present:
        raise AuditError("a trusted main NVD artifact is required")
    _create_owned_directory(work, label="NVD audit work directory")
    try:
        _analyze_copy(
            trusted,
            work / "scan",
            run_task,
        )
    except (AuditError, OSError):
        _remove_owned_directory(work)
        raise
    return "trusted-artifact"


def produce_dependency_database(
    *,
    output: Path,
    seed: Path | None = None,
    run_task: TaskRunner,
    plugin_version: str,
    contract_digest: str,
) -> None:
    """Produce a validated database for upload by the trusted main workflow."""
    _refresh_and_analyze(
        output,
        run_task,
        plugin_version=plugin_version,
        contract_digest=contract_digest,
        seed=seed,
    )


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
        child_environment = os.environ.copy()
        if task != "dependencyCheckUpdate":
            child_environment.pop("NVD_API_KEY", None)
        try:
            process = subprocess.Popen(
                command,
                cwd=gradlew.parent,
                env=child_environment,
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
                    gradlew.parent / "build" / "reports" / "dependency-check-scope.json",
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
    produce.add_argument("--plugin-version", required=True)
    produce.add_argument("--contract-digest", required=True)
    produce.add_argument("--output-dir", type=Path, required=True)
    produce.add_argument("--seed-dir", type=Path, required=True)
    produce.add_argument("--seed-present", required=True)

    metadata = commands.add_parser("metadata")
    metadata.add_argument("--catalog", type=Path, required=True)
    metadata.add_argument("--repository-root", type=Path, required=True)
    metadata.add_argument("--contract", type=Path, required=True)
    metadata.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "metadata":
        try:
            values = _dependency_artifact_metadata(
                args.catalog,
                repository_root=args.repository_root,
                contract=args.contract,
            )
            with args.output.open("a", encoding="utf-8") as handle:
                for key, value in values.items():
                    handle.write(f"{key}={value}\n")
            return 0
        except (AuditError, OSError) as exc:
            print(f"Android dependency metadata failed: {exc}", file=sys.stderr)
            return 1
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
                plugin_version=args.plugin_version,
                contract_digest=args.contract_digest,
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
            run_task=run_task,
        )
        print(f"Android dependency audit completed via {mode}.")
        return 0
    except (AuditError, OSError) as exc:
        print(f"Android dependency audit failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
