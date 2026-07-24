"""Run the Android dependency audit without mutating its trusted NVD cache."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

FRESHNESS_MARKER = ".xpj-nvd-last-successful-update"
DEFAULT_MAX_STALE_HOURS = 48


class AuditError(RuntimeError):
    """The dependency audit could not prove a safe result."""


TaskRunner = Callable[[str, Path], int]


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _copy_database(source: Path, target: Path) -> None:
    _remove_tree(target)
    shutil.copytree(source, target)


def _require_fresh_database(
    database: Path,
    *,
    now: int,
    max_stale_seconds: int,
) -> None:
    marker = database / FRESHNESS_MARKER
    if not database.is_dir() or not marker.is_file():
        raise AuditError("no validated NVD database is available")
    try:
        updated_at = int(marker.read_text(encoding="ascii").strip())
    except ValueError as exc:
        raise AuditError("the NVD freshness marker is invalid") from exc
    age = now - updated_at
    if age < -300 or age > max_stale_seconds:
        raise AuditError("the validated NVD database is outside the freshness window")


def _analyze_copy(
    trusted: Path,
    scan: Path,
    run_task: TaskRunner,
) -> None:
    _copy_database(trusted, scan)
    if run_task("dependencyCheckAnalyze", scan) != 0:
        raise AuditError("dependency analysis failed")


def _promote(candidate: Path, trusted: Path) -> None:
    backup = trusted.with_name(f"{trusted.name}.previous")
    _remove_tree(backup)
    if trusted.exists():
        trusted.rename(backup)
    try:
        candidate.rename(trusted)
    except OSError:
        if backup.exists() and not trusted.exists():
            backup.rename(trusted)
        raise
    _remove_tree(backup)


def run_dependency_audit(
    *,
    trusted: Path,
    work: Path,
    cache_hit: bool,
    has_api_key: bool,
    run_task: TaskRunner,
    now: int,
    max_stale_hours: int = DEFAULT_MAX_STALE_HOURS,
) -> bool:
    """Return whether a newly validated database should be saved to cache."""
    max_stale_seconds = max_stale_hours * 60 * 60
    if cache_hit:
        _require_fresh_database(
            trusted,
            now=now,
            max_stale_seconds=max_stale_seconds,
        )
        _analyze_copy(trusted, work / "scan", run_task)
        return False

    if not has_api_key:
        _require_fresh_database(
            trusted,
            now=now,
            max_stale_seconds=max_stale_seconds,
        )
        _analyze_copy(trusted, work / "scan", run_task)
        return False

    candidate = work / "candidate"
    _remove_tree(candidate)
    if trusted.is_dir():
        shutil.copytree(trusted, candidate)
    else:
        candidate.mkdir(parents=True)
    if run_task("dependencyCheckUpdate", candidate) != 0:
        raise AuditError("NVD update failed")
    (candidate / FRESHNESS_MARKER).write_text(f"{now}\n", encoding="ascii")
    if run_task("dependencyCheckAnalyze", candidate) != 0:
        raise AuditError("dependency analysis failed")
    _promote(candidate, trusted)
    return True


def _run_gradle_factory(
    gradlew: Path,
    log_path: Path,
) -> TaskRunner:
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
            completed = subprocess.run(
                command,
                cwd=gradlew.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            output = completed.stdout
            return_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode(errors="replace")
            output += f"\n{task} timed out after {timeout_seconds} seconds\n"
            return_code = 124
        print(output, end="")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(output)
        return return_code

    return run_task


def _parse_cache_hit(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false", ""}:
        raise AuditError(f"invalid cache-hit value: {value!r}")
    return normalized == "true"


def _write_output(path: Path, *, save_cache: bool) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"cache-save={'true' if save_cache else 'false'}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gradlew", type=Path, required=True)
    parser.add_argument("--trusted-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--cache-hit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()

    gradlew = args.gradlew.resolve()
    trusted = args.trusted_dir.resolve()
    work = args.work_dir.resolve()
    if trusted == work or trusted in work.parents or work in trusted.parents:
        parser.error("trusted-dir and work-dir must be separate trees")
    _remove_tree(work)
    work.mkdir(parents=True)
    args.log.write_text("", encoding="utf-8")
    try:
        save_cache = run_dependency_audit(
            trusted=trusted,
            work=work,
            cache_hit=_parse_cache_hit(args.cache_hit),
            has_api_key=bool(os.environ.get("NVD_API_KEY", "").strip()),
            run_task=_run_gradle_factory(gradlew, args.log),
            now=int(time.time()),
        )
    except AuditError as exc:
        print(f"Android dependency audit failed: {exc}", file=sys.stderr)
        return 1
    _write_output(args.output, save_cache=save_cache)
    return 0


if __name__ == "__main__":
    sys.exit(main())
