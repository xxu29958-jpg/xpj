"""Run Android dependency audits from trusted or freshly downloaded NVD data."""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path


class AuditError(RuntimeError):
    """The dependency audit could not prove a safe result."""


class ArtifactError(AuditError):
    """The downloaded artifact does not contain a usable NVD database."""


TaskRunner = Callable[[str, Path], int]


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _require_database_payload(database: Path) -> None:
    if not database.is_dir():
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


def _copy_database(source: Path, target: Path) -> None:
    _require_database_payload(source)
    _remove_tree(target)
    try:
        shutil.copytree(source, target)
    except OSError as exc:
        _remove_tree(target)
        raise ArtifactError("the NVD artifact could not be copied") from exc


def _analyze_copy(trusted: Path, scan: Path, run_task: TaskRunner) -> None:
    _copy_database(trusted, scan)
    if run_task("dependencyCheckAnalyze", scan) != 0:
        raise AuditError("dependency analysis failed")


def _refresh_and_analyze(destination: Path, run_task: TaskRunner) -> None:
    _remove_tree(destination)
    destination.mkdir(parents=True)
    try:
        if run_task("dependencyCheckUpdate", destination) != 0:
            raise AuditError("NVD update failed")
        _require_database_payload(destination)
        if run_task("dependencyCheckAnalyze", destination) != 0:
            raise AuditError("dependency analysis failed")
        _require_database_payload(destination)
    except (AuditError, OSError):
        _remove_tree(destination)
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


def produce_dependency_database(*, output: Path, run_task: TaskRunner) -> None:
    """Produce a validated database for upload by the trusted main workflow."""
    _refresh_and_analyze(output, run_task)


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


def _run_gradle_factory(gradlew: Path, log_path: Path) -> TaskRunner:
    def run_task(task: str, database: Path) -> int:
        command = [
            str(gradlew),
            "--no-daemon",
            "--max-workers=2",
            task,
            f"-PdependencyCheckDataDir={database}",
        ]
        timeout_seconds = 12 * 60 if task == "dependencyCheckUpdate" else 10 * 60
        if task == "dependencyCheckUpdate":
            command.append("-PdependencyCheckNvdValidForHours=0")
        else:
            command.append("-PdependencyCheckAutoUpdate=false")
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
            output, _ = process.communicate()
            output += f"\n{task} timed out after {timeout_seconds} seconds\n"
            return_code = 124
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
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    gradlew = args.gradlew.resolve()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("", encoding="utf-8")
    run_task = _run_gradle_factory(gradlew, args.log)
    try:
        if args.command == "produce":
            if not os.environ.get("NVD_API_KEY", "").strip():
                raise AuditError("NVD_API_KEY is required to produce the trusted artifact")
            produce_dependency_database(
                output=args.output_dir.resolve(),
                run_task=run_task,
            )
            return 0

        trusted = args.trusted_dir.resolve()
        work = args.work_dir.resolve()
        if trusted == work or trusted in work.parents or work in trusted.parents:
            parser.error("trusted-dir and work-dir must be separate trees")
        _remove_tree(work)
        work.mkdir(parents=True)
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
