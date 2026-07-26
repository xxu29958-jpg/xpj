#!/usr/bin/env python3
"""Reject connected-test runs that added a fatal Android process exit."""

from __future__ import annotations

import argparse
import collections
import dataclasses
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

ANDROID_PROCESS_ATTRIBUTE = "{http://schemas.android.com/apk/res/android}process"
EXIT_INFO_HEADER = "ACTIVITY MANAGER PROCESS EXIT INFO"
TARGET_HEADER_PREFIX = "===== Android target "
EXIT_RECORD_HEADER_PATTERN = re.compile(r"ApplicationExitInfo #\d+:")
FATAL_EXIT_REASONS = {
    4: "crash",
    5: "native crash",
    6: "ANR",
    7: "initialization failure",
}


class EvidenceError(RuntimeError):
    """Connected-test evidence is missing, ambiguous, or malformed."""


@dataclasses.dataclass(frozen=True)
class ExitRecord:
    target: str
    package: str
    timestamp: str
    pid: int
    process: str
    reason: int
    status: int


@dataclasses.dataclass(frozen=True)
class ExitSnapshot:
    targets: frozenset[str]
    records: tuple[ExitRecord, ...]


def _field(text: str, name: str, next_fields: Iterable[str]) -> str | None:
    marker = f"{name}="
    start = text.find(marker)
    if start < 0:
        return None
    value_start = start + len(marker)
    ends = [
        position
        for next_name in next_fields
        if (position := text.find(f" {next_name}=", value_start)) >= 0
    ]
    value_end = min(ends, default=len(text))
    return text[value_start:value_end].strip()


def _parse_record(
    lines: list[str],
    *,
    target: str | None,
    package: str | None,
) -> ExitRecord:
    if target is None or package is None:
        raise EvidenceError("ApplicationExitInfo record is outside a target/package block.")
    normalized = " ".join(line.strip() for line in lines)
    fields = {
        "timestamp": _field(normalized, "timestamp", ("pid",)),
        "pid": _field(normalized, "pid", ("realUid",)),
        "process": _field(normalized, "process", ("reason",)),
        "reason": _field(normalized, "reason", ("subreason", "status")),
        "status": _field(normalized, "status", ("importance",)),
    }
    missing = [name for name, value in fields.items() if value is None]
    if missing:
        raise EvidenceError(
            "ApplicationExitInfo record is missing " + ", ".join(sorted(missing)) + "."
        )
    try:
        pid = int(fields["pid"])
        reason = int(fields["reason"].split(maxsplit=1)[0])
        status = int(fields["status"].split(maxsplit=1)[0])
    except (AttributeError, ValueError) as exc:
        raise EvidenceError("ApplicationExitInfo numeric fields are malformed.") from exc
    return ExitRecord(
        target=target,
        package=package,
        timestamp=fields["timestamp"],
        pid=pid,
        process=fields["process"],
        reason=reason,
        status=status,
    )


def parse_exit_snapshot(text: str) -> ExitSnapshot:
    targets: set[str] = set()
    targets_with_header: set[str] = set()
    records: list[ExitRecord] = []
    target: str | None = None
    package: str | None = None
    record_lines: list[str] | None = None

    def finish_record() -> None:
        nonlocal record_lines
        if record_lines is not None:
            records.append(_parse_record(record_lines, target=target, package=package))
            record_lines = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(TARGET_HEADER_PREFIX) and line.endswith(" ====="):
            finish_record()
            target = line[len(TARGET_HEADER_PREFIX) : -len(" =====")].strip()
            if not target:
                raise EvidenceError("Connected-test target marker is empty.")
            targets.add(target)
            package = None
            continue
        if EXIT_INFO_HEADER in line:
            if target is None:
                raise EvidenceError("Exit-info output has no connected-test target marker.")
            targets_with_header.add(target)
            continue
        if line.startswith("package:"):
            finish_record()
            package = line.removeprefix("package:").strip()
            if not package:
                raise EvidenceError("Exit-info package block is empty.")
            continue
        if line.startswith("ApplicationExitInfo"):
            if EXIT_RECORD_HEADER_PATTERN.fullmatch(line) is None:
                raise EvidenceError(
                    f"ApplicationExitInfo record header is malformed: {line!r}."
                )
            finish_record()
            record_lines = []
            continue
        if record_lines is not None:
            record_lines.append(line)
    finish_record()

    if not targets:
        raise EvidenceError("Connected-test exit-info evidence has no target markers.")
    missing_headers = targets - targets_with_header
    if missing_headers:
        raise EvidenceError(
            "Exit-info command did not return its contract header for target(s): "
            + ", ".join(sorted(missing_headers))
            + "."
        )
    return ExitSnapshot(targets=frozenset(targets), records=tuple(records))


def application_processes(application_id: str, manifest_text: str) -> set[str]:
    application_id = application_id.strip()
    if not application_id:
        raise EvidenceError("APK application id is empty.")
    try:
        root = ET.fromstring(manifest_text)
    except ET.ParseError as exc:
        raise EvidenceError("APK manifest XML is malformed.") from exc
    processes = {application_id}
    for element in root.iter():
        raw_process = element.attrib.get(ANDROID_PROCESS_ATTRIBUTE)
        if not raw_process:
            continue
        if raw_process.startswith((".", ":")):
            processes.add(application_id + raw_process)
        else:
            processes.add(raw_process)
    return processes


def _run_apkanalyzer(apkanalyzer: Path, *args: str) -> str:
    completed = subprocess.run(
        [str(apkanalyzer), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise EvidenceError(
            f"apkanalyzer {' '.join(args)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout


def _single_apk(output_dir: Path) -> Path:
    apk_files = sorted(path for path in output_dir.rglob("*.apk") if path.is_file())
    if len(apk_files) != 1:
        raise EvidenceError(
            f"Expected exactly one APK under {output_dir}; found {len(apk_files)}."
        )
    return apk_files[0]


def expected_processes(apkanalyzer: Path, apk_output_dirs: Iterable[Path]) -> set[str]:
    processes: set[str] = set()
    for output_dir in apk_output_dirs:
        apk = _single_apk(output_dir)
        application_id = _run_apkanalyzer(
            apkanalyzer,
            "manifest",
            "application-id",
            str(apk),
        )
        manifest = _run_apkanalyzer(
            apkanalyzer,
            "manifest",
            "print",
            str(apk),
        )
        processes.update(application_processes(application_id, manifest))
    if not processes:
        raise EvidenceError("No connected-test process identities were derived from APKs.")
    return processes


def new_fatal_exits(
    before: ExitSnapshot,
    after: ExitSnapshot,
    expected: set[str],
) -> list[ExitRecord]:
    new_records = new_exit_records(before, after)
    return sorted(
        (
            record
            for record in new_records
            if record.process in expected and record.reason in FATAL_EXIT_REASONS
        ),
        key=lambda record: (
            record.target,
            record.timestamp,
            record.process,
            record.pid,
        ),
    )


def new_exit_records(
    before: ExitSnapshot,
    after: ExitSnapshot,
) -> list[ExitRecord]:
    if before.targets != after.targets:
        raise EvidenceError(
            "Connected-test target set changed while collecting exit evidence."
        )
    new_records = collections.Counter(after.records) - collections.Counter(before.records)
    return sorted(
        new_records.elements(),
        key=lambda record: (
            record.target,
            record.timestamp,
            record.process,
            record.pid,
        ),
    )


def require_expected_process_exit(
    records: Iterable[ExitRecord],
    expected: set[str],
) -> int:
    expected_record_count = sum(record.process in expected for record in records)
    if expected_record_count == 0:
        raise EvidenceError(
            "Post-test exit evidence contains no new target or instrumentation "
            "process record; APK uninstall may have erased the evidence."
        )
    return expected_record_count


def verify(
    *,
    before_path: Path,
    after_path: Path,
    apkanalyzer: Path,
    apk_output_dirs: Iterable[Path],
) -> int:
    try:
        before_text = before_path.read_text(encoding="utf-8")
        after_text = after_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceError(f"Connected-test exit evidence is unreadable: {exc}") from exc
    before = parse_exit_snapshot(before_text)
    after = parse_exit_snapshot(after_text)
    expected = expected_processes(apkanalyzer, apk_output_dirs)
    expected_record_count = require_expected_process_exit(
        new_exit_records(before, after),
        expected,
    )
    failures = new_fatal_exits(before, after, expected)
    if failures:
        details = "\n".join(
            "  "
            f"{record.target}: {record.process} "
            f"{FATAL_EXIT_REASONS[record.reason]} "
            f"(reason={record.reason}, status={record.status}, "
            f"pid={record.pid}, timestamp={record.timestamp})"
            for record in failures
        )
        raise EvidenceError(
            "Connected tests produced fatal process exit record(s):\n" + details
        )
    return expected_record_count


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--apkanalyzer", required=True, type=Path)
    parser.add_argument("--apk-output-dir", action="append", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        expected_record_count = verify(
            before_path=args.before,
            after_path=args.after,
            apkanalyzer=args.apkanalyzer,
            apk_output_dirs=args.apk_output_dir,
        )
    except EvidenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "Connected process exit evidence is healthy "
        f"({expected_record_count} new expected process record(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
