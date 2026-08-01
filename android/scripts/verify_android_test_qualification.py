#!/usr/bin/env python3
"""Qualify Android JVM and connected tests from their executed results."""

from __future__ import annotations

import argparse
import collections
import dataclasses
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from collections.abc import Iterable, Mapping

ANDROID_PROCESS_ATTRIBUTE = "{http://schemas.android.com/apk/res/android}process"
EXIT_INFO_HEADER = "ACTIVITY MANAGER PROCESS EXIT INFO"
TARGET_HEADER_PREFIX = "===== Android target "
EXIT_RECORD_HEADER_PATTERN = re.compile(r"ApplicationExitInfo #\d+:")
EXPECTED_EXIT_STATUSES = {
    1: frozenset({0}),  # REASON_EXIT_SELF
    10: frozenset({0}),  # REASON_USER_REQUESTED
    15: frozenset({0}),  # REASON_PACKAGE_STATE_CHANGE
    16: frozenset({0}),  # REASON_PACKAGE_UPDATED
}
REASON_OTHER = 13
NORMAL_EXIT_STATUS = 0


class EvidenceError(RuntimeError):
    """Android test evidence is missing, ambiguous, or malformed."""


@dataclasses.dataclass(frozen=True)
class TestResultSummary:
    tests: int
    skipped: int
    files: int


TEST_LANES = ("jvm", "instrumentation")
CI_CONTEXT_MARKERS = (
    "CI",
    "GITHUB_ACTIONS",
    "GITHUB_BASE_REF",
    "GITHUB_EVENT_NAME",
    "GITHUB_SHA",
    "GITEA_ACTIONS",
)


def parse_test_baseline(
    text: str,
    source: str,
    *,
    legacy_scalar_lane: str | None = None,
) -> dict[str, int]:
    meaningful_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith(("#", "!"))
    ]
    if legacy_scalar_lane is not None and len(meaningful_lines) == 1:
        try:
            legacy_value = int(meaningful_lines[0])
        except ValueError:
            pass
        else:
            if legacy_scalar_lane not in TEST_LANES or legacy_value < 0:
                raise EvidenceError(
                    f"Legacy Android test baseline at {source} is invalid."
                )
            return {
                lane: legacy_value if lane == legacy_scalar_lane else 0
                for lane in TEST_LANES
            }

    values: dict[str, int] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        value = raw_value.strip()
        if not separator or not key or key in values:
            raise EvidenceError(
                f"Android test baseline at {source}:{line_number} is malformed."
            )
        try:
            parsed = int(value)
        except ValueError as exc:
            raise EvidenceError(
                f"Android test baseline '{key}' at {source} must be an integer."
            ) from exc
        if parsed < 0:
            raise EvidenceError(
                f"Android test baseline '{key}' at {source} must be non-negative."
            )
        values[key] = parsed
    if set(values) != set(TEST_LANES):
        raise EvidenceError(
            f"Android test baseline at {source} must contain exactly "
            f"{', '.join(TEST_LANES)}."
        )
    return values


def read_test_baseline(path: Path) -> dict[str, int]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceError(f"Android test baseline is unreadable: {exc}") from exc
    return parse_test_baseline(text, str(path))


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _suite_count(suite: ET.Element, name: str, result_file: Path) -> int:
    raw_value = suite.attrib.get(name)
    if raw_value is None:
        raise EvidenceError(
            f"JUnit XML testsuite is missing '{name}': {result_file}"
        )
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise EvidenceError(
            f"JUnit XML testsuite has a malformed '{name}' count: {result_file}"
        ) from exc
    if value < 0:
        raise EvidenceError(
            f"JUnit XML testsuite has a negative '{name}' count: {result_file}"
        )
    return value


def read_test_results(results_dir: Path) -> TestResultSummary:
    if not results_dir.is_dir():
        raise EvidenceError(f"Android test result directory is missing: {results_dir}")
    result_files = sorted(
        path
        for path in results_dir.rglob("TEST-*.xml")
        if path.is_file()
    )
    if not result_files:
        raise EvidenceError(f"No JUnit XML results were found under {results_dir}.")

    identities: set[tuple[str, str]] = set()
    skipped = 0
    for result_file in result_files:
        try:
            root = ET.parse(result_file).getroot()
        except (ET.ParseError, OSError) as exc:
            raise EvidenceError(
                f"JUnit XML result is unreadable or malformed: {result_file}"
            ) from exc
        if _xml_local_name(root.tag) not in {"testsuite", "testsuites"}:
            raise EvidenceError(
                f"JUnit XML result has an unsupported root element: {result_file}"
            )
        testcases = [
            element
            for element in root.iter()
            if _xml_local_name(element.tag) == "testcase"
        ]
        if not testcases:
            raise EvidenceError(f"JUnit XML result contains no test cases: {result_file}")
        suites = [
            element
            for element in root.iter()
            if _xml_local_name(element.tag) in {"testsuite", "testsuites"}
        ]
        if not suites:
            raise EvidenceError(
                f"JUnit XML result contains no suite summary elements: {result_file}"
            )
        for suite in suites:
            suite_testcases = [
                element
                for element in suite.iter()
                if _xml_local_name(element.tag) == "testcase"
            ]
            declared = {
                name: _suite_count(suite, name, result_file)
                for name in ("tests", "failures", "errors", "skipped")
            }
            observed = {
                "tests": len(suite_testcases),
                "failures": sum(
                    any(_xml_local_name(child.tag) == "failure" for child in testcase)
                    for testcase in suite_testcases
                ),
                "errors": sum(
                    any(_xml_local_name(child.tag) == "error" for child in testcase)
                    for testcase in suite_testcases
                ),
                "skipped": sum(
                    any(_xml_local_name(child.tag) == "skipped" for child in testcase)
                    for testcase in suite_testcases
                ),
            }
            if declared != observed:
                raise EvidenceError(
                    f"JUnit XML result summary mismatch in {result_file}: "
                    f"declared={declared}, observed={observed}."
                )
            if declared["failures"] or declared["errors"]:
                raise EvidenceError(
                    f"JUnit XML reports failed tests in {result_file}: "
                    f"failures={declared['failures']}, errors={declared['errors']}."
                )
        skipped += sum(
            any(_xml_local_name(child.tag) == "skipped" for child in testcase)
            for testcase in testcases
        )
        for testcase in testcases:
            class_name = (
                testcase.attrib.get("classname")
                or testcase.attrib.get("className")
                or ""
            ).strip()
            test_name = testcase.attrib.get("name", "").strip()
            if not class_name or not test_name:
                raise EvidenceError(
                    f"JUnit XML result has a test case without class/name: {result_file}"
                )
            identity = (class_name, test_name)
            if identity in identities:
                raise EvidenceError(
                    "JUnit XML results contain a duplicate test case: "
                    f"{class_name}.{test_name}."
                )
            identities.add(identity)
    return TestResultSummary(
        tests=len(identities),
        skipped=skipped,
        files=len(result_files),
    )


def verify_test_results(
    *,
    lane: str,
    baseline_path: Path,
    results_dir: Path,
) -> TestResultSummary:
    if lane not in TEST_LANES:
        raise EvidenceError(f"Unknown Android test lane: {lane}")
    baseline = read_test_baseline(baseline_path)
    summary = read_test_results(results_dir)
    if summary.skipped:
        raise EvidenceError(
            f"Android {lane} results contain skipped tests: "
            f"skipped={summary.skipped}. Skipped cases are not execution evidence."
        )
    expected = baseline[lane]
    if summary.tests != expected:
        raise EvidenceError(
            f"Android {lane} executed-result count mismatch: "
            f"actual={summary.tests}, baseline={expected}. "
            "Update the baseline in the same change only when the test change is intentional."
        )
    return summary


def _run_git(repository_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError(f"Could not run git {' '.join(args)}: {exc}") from exc


def verify_baseline_ratchet(
    *,
    baseline_path: Path,
    repository_root: Path,
    environment: Mapping[str, str] = os.environ,
) -> tuple[dict[str, int], dict[str, int] | None, str]:
    repository_root = repository_root.resolve()
    baseline_path = baseline_path.resolve()
    try:
        baseline_repo_path = baseline_path.relative_to(repository_root).as_posix()
    except ValueError as exc:
        raise EvidenceError("Android test baseline is outside the repository.") from exc
    current = read_test_baseline(baseline_path)

    explicit_ref = environment.get("XPJ_AUDIT_BASE_REF", "").strip()
    in_ci = any(environment.get(marker, "").strip() for marker in CI_CONTEXT_MARKERS)
    if explicit_ref:
        base_ref = explicit_ref
    elif in_ci:
        raise EvidenceError(
            "CI requires XPJ_AUDIT_BASE_REF with the exact pre-change commit."
        )
    else:
        base_ref = environment.get(
            "XPJ_AUDIT_DEFAULT_REF",
            "refs/remotes/origin/main",
        ).strip()

    reachable = _run_git(
        repository_root,
        "rev-parse",
        "--verify",
        f"{base_ref}^{{commit}}",
    )
    if reachable.returncode != 0:
        if explicit_ref:
            raise EvidenceError(
                f"Android test baseline base ref '{base_ref}' is unreachable."
            )
        return current, None, base_ref
    base_commit = reachable.stdout.strip()
    if not base_commit:
        raise EvidenceError(
            f"Android test baseline base ref '{base_ref}' resolved without a commit."
        )
    if in_ci:
        head = _run_git(repository_root, "rev-parse", "--verify", "HEAD^{commit}")
        head_commit = head.stdout.strip()
        if head.returncode != 0 or not head_commit:
            raise EvidenceError("Could not resolve Android qualification HEAD.")
        if base_commit == head_commit:
            raise EvidenceError(
                "Android test baseline base must precede HEAD; "
                "self-comparison is forbidden."
            )
        ancestry = _run_git(
            repository_root,
            "merge-base",
            "--is-ancestor",
            base_commit,
            head_commit,
        )
        if ancestry.returncode != 0:
            raise EvidenceError(
                "Android test baseline base must be an ancestor of qualification HEAD."
            )

    listed = _run_git(
        repository_root,
        "ls-tree",
        "--name-only",
        base_commit,
        "--",
        baseline_repo_path,
    )
    if listed.returncode != 0:
        raise EvidenceError(
            f"Could not inspect Android test baseline at '{base_ref}': "
            f"{listed.stderr.strip()}"
        )
    listed_paths = [line for line in listed.stdout.splitlines() if line.strip()]
    if not listed_paths:
        return current, None, base_ref
    if listed_paths != [baseline_repo_path]:
        raise EvidenceError(
            f"Unexpected Android test baseline tree result at '{base_ref}'."
        )

    shown = _run_git(
        repository_root,
        "show",
        f"{base_commit}:{baseline_repo_path}",
    )
    if shown.returncode != 0 or not shown.stdout.strip():
        raise EvidenceError(
            f"Could not read Android test baseline at '{base_ref}'."
        )
    base = parse_test_baseline(
        shown.stdout,
        f"{base_ref}:{baseline_repo_path}",
        legacy_scalar_lane="jvm",
    )
    drops = {
        lane: (base[lane], current[lane])
        for lane in TEST_LANES
        if current[lane] < base[lane]
    }
    if drops:
        details = "; ".join(
            f"{lane} base={old} current={new}"
            for lane, (old, new) in drops.items()
        )
        raise EvidenceError(
            "Android test baseline ratchet rejected a decrease: " + details
        )
    return current, base, base_ref


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
    try:
        completed = subprocess.run(
            [str(apkanalyzer), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise EvidenceError(
            f"Could not run apkanalyzer {' '.join(args)}: {exc}"
        ) from exc
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


def new_unhealthy_exits(
    before: ExitSnapshot,
    after: ExitSnapshot,
    expected: set[str],
    *,
    instrumentation_cleanup_processes: set[str] | frozenset[str] = frozenset(),
) -> list[ExitRecord]:
    new_records = new_exit_records(before, after)
    return sorted(
        (
            record
            for record in new_records
            if record.process in expected
            # API 36 can report the Android Gradle Plugin's post-test removal of
            # the instrumentation APK as REASON_OTHER/status=0. Scope that
            # normal cleanup exception to processes derived from the test APK;
            # the product APK still fails closed on REASON_OTHER. Android's
            # human-readable description is deliberately not parsed because
            # the platform contract does not guarantee its format.
            and not (
                record.process in instrumentation_cleanup_processes
                and record.reason == REASON_OTHER
                and record.status == NORMAL_EXIT_STATUS
            )
            and record.status
            not in EXPECTED_EXIT_STATUSES.get(record.reason, frozenset())
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


def verify_process_health(
    *,
    before_path: Path,
    after_path: Path,
    apkanalyzer: Path,
    target_apk_output_dir: Path,
    instrumentation_apk_output_dir: Path,
) -> int:
    try:
        before_text = before_path.read_text(encoding="utf-8")
        after_text = after_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceError(f"Connected-test exit evidence is unreadable: {exc}") from exc
    before = parse_exit_snapshot(before_text)
    after = parse_exit_snapshot(after_text)
    target_processes = expected_processes(apkanalyzer, (target_apk_output_dir,))
    instrumentation_processes = expected_processes(
        apkanalyzer,
        (instrumentation_apk_output_dir,),
    )
    expected = target_processes | instrumentation_processes
    expected_record_count = require_expected_process_exit(
        new_exit_records(before, after),
        expected,
    )
    failures = new_unhealthy_exits(
        before,
        after,
        expected,
        instrumentation_cleanup_processes=instrumentation_processes,
    )
    if failures:
        details = "\n".join(
            "  "
            f"{record.target}: {record.process} "
            "unexpected exit "
            f"(reason={record.reason}, status={record.status}, "
            f"pid={record.pid}, timestamp={record.timestamp})"
            for record in failures
        )
        raise EvidenceError(
            "Connected tests produced unhealthy process exit record(s):\n" + details
        )
    return expected_record_count


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    baseline = subparsers.add_parser("baseline")
    baseline.add_argument("--baseline", required=True, type=Path)
    baseline.add_argument("--repository-root", required=True, type=Path)

    results = subparsers.add_parser("results")
    results.add_argument("--lane", choices=TEST_LANES, required=True)
    results.add_argument("--baseline", required=True, type=Path)
    results.add_argument("--results-dir", required=True, type=Path)

    connected = subparsers.add_parser("connected")
    connected.add_argument("--baseline", required=True, type=Path)
    connected.add_argument("--results-dir", required=True, type=Path)
    connected.add_argument("--before", required=True, type=Path)
    connected.add_argument("--after", required=True, type=Path)
    connected.add_argument("--apkanalyzer", required=True, type=Path)
    connected.add_argument("--target-apk-output-dir", required=True, type=Path)
    connected.add_argument(
        "--instrumentation-apk-output-dir",
        required=True,
        type=Path,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "baseline":
            current, base, base_ref = verify_baseline_ratchet(
                baseline_path=args.baseline,
                repository_root=args.repository_root,
            )
            if base is None:
                print(
                    "Android test baselines are valid "
                    f"({current}; base '{base_ref}' unavailable or bootstrapping)."
                )
            else:
                print(
                    "Android test baseline ratchet is healthy "
                    f"(current={current}, base={base})."
                )
            return 0
        if args.command == "results":
            summary = verify_test_results(
                lane=args.lane,
                baseline_path=args.baseline,
                results_dir=args.results_dir,
            )
            print(
                f"Android {args.lane} executed-result count is healthy "
                f"({summary.tests} tests, {summary.skipped} skipped, "
                f"{summary.files} XML files)."
            )
            return 0

        summary = verify_test_results(
            lane="instrumentation",
            baseline_path=args.baseline,
            results_dir=args.results_dir,
        )
        expected_record_count = verify_process_health(
            before_path=args.before,
            after_path=args.after,
            apkanalyzer=args.apkanalyzer,
            target_apk_output_dir=args.target_apk_output_dir,
            instrumentation_apk_output_dir=args.instrumentation_apk_output_dir,
        )
    except EvidenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "Android connected qualification is healthy "
        f"({summary.tests} tests, {summary.skipped} skipped, "
        f"{expected_record_count} new expected process record(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
