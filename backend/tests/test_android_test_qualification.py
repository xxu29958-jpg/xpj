from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPOSITORY_ROOT / "android" / "scripts" / "verify_android_test_qualification.py"
)


def _load_script() -> object:
    spec = importlib.util.spec_from_file_location(
        "_test_android_test_qualification",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualification = _load_script()


def _snapshot(records: str) -> str:
    return f"""
===== Android target emulator-5554 =====
ACTIVITY MANAGER PROCESS EXIT INFO (dumpsys activity exit-info)
 package: com.ticketbox
  Historical Process Exit for uid=10123
{records}
"""


def _write_results(
    path: Path,
    testcases: str,
    *,
    tests: int,
    failures: int = 0,
    errors: int = 0,
    skipped: int = 0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            f'<testsuite name="suite" tests="{tests}" failures="{failures}" '
            f'errors="{errors}" skipped="{skipped}">{testcases}</testsuite>'
        ),
        encoding="utf-8",
    )


def _old_record(
    *,
    timestamp: str = "2026-07-26 12:00:00.000",
    pid: int = 123,
    process: str = "com.ticketbox",
    reason: int = 4,
    status: int = 0,
) -> str:
    return f"""   ApplicationExitInfo #0:
    timestamp={timestamp}
    pid={pid}
    realUid=10123
    process={process}
    reason={reason} (APP CRASH)
    status={status}
"""


def _new_record(
    *,
    timestamp: str = "2026-07-26 12:00:00.000",
    pid: int = 123,
    process: str = "com.ticketbox",
    reason: int = 5,
    status: int = 11,
) -> str:
    return f"""   ApplicationExitInfo #0:
     timestamp={timestamp} pid={pid} realUid=10123 packageUid=10123
     process={process} reason={reason} (APP CRASH(NATIVE)) subreason=0 status={status}
     importance=100 pss=1MB rss=2MB description=null state=empty trace=null
"""


def test_exit_snapshot_parser_supports_android_dump_layouts() -> None:
    snapshot = qualification.parse_exit_snapshot(
        _snapshot(_old_record() + _new_record(pid=456))
    )

    assert snapshot.targets == {"emulator-5554"}
    assert [(record.pid, record.reason) for record in snapshot.records] == [
        (123, 4),
        (456, 5),
    ]


def test_new_native_crash_is_a_failure() -> None:
    before = qualification.parse_exit_snapshot(_snapshot(""))
    after = qualification.parse_exit_snapshot(_snapshot(_new_record()))

    failures = qualification.new_fatal_exits(
        before,
        after,
        {"com.ticketbox"},
    )

    assert [(record.process, record.reason) for record in failures] == [
        ("com.ticketbox", 5)
    ]


def test_stale_crash_from_before_the_run_is_ignored() -> None:
    evidence = _snapshot(_old_record())
    before = qualification.parse_exit_snapshot(evidence)
    after = qualification.parse_exit_snapshot(evidence)

    assert qualification.new_fatal_exits(before, after, {"com.ticketbox"}) == []
    with pytest.raises(qualification.EvidenceError, match="no new target"):
        qualification.require_expected_process_exit(
            qualification.new_exit_records(before, after),
            {"com.ticketbox"},
        )


@pytest.mark.parametrize("reason", [4, 5, 6, 7])
def test_each_android_fatal_exit_reason_is_rejected(reason: int) -> None:
    before = qualification.parse_exit_snapshot(_snapshot(""))
    after = qualification.parse_exit_snapshot(
        _snapshot(_new_record(reason=reason))
    )

    failures = qualification.new_fatal_exits(
        before,
        after,
        {"com.ticketbox"},
    )

    assert [record.reason for record in failures] == [reason]


def test_unrelated_process_exit_is_ignored() -> None:
    before = qualification.parse_exit_snapshot(_snapshot(""))
    after = qualification.parse_exit_snapshot(
        _snapshot(
            _new_record(process="com.ticketbox", reason=10, status=0)
            + _new_record(process="com.android.systemui", pid=456)
        )
    )

    assert (
        qualification.require_expected_process_exit(
            qualification.new_exit_records(before, after),
            {"com.ticketbox"},
        )
        == 1
    )
    assert qualification.new_fatal_exits(before, after, {"com.ticketbox"}) == []


def test_exit_snapshot_fails_closed_on_malformed_evidence() -> None:
    with pytest.raises(qualification.EvidenceError, match="missing status"):
        qualification.parse_exit_snapshot(
            _snapshot(
                """   ApplicationExitInfo #0:
    timestamp=2026-07-26 12:00:00.000
    pid=123
    process=com.ticketbox
    reason=4 (APP CRASH)
"""
            )
        )
    malformed_header = _old_record().replace(
        "ApplicationExitInfo #0:",
        "ApplicationExitInfo #0",
    )
    with pytest.raises(qualification.EvidenceError, match="header is malformed"):
        qualification.parse_exit_snapshot(_snapshot(malformed_header))


def test_manifest_processes_are_derived_without_hardcoded_package_names() -> None:
    manifest = """
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <application>
    <service android:process=":sync" />
    <provider android:process="shared.worker" />
  </application>
</manifest>
"""

    assert qualification.application_processes("family.finance", manifest) == {
        "family.finance",
        "family.finance:sync",
        "shared.worker",
    }


def test_junit_results_count_reported_cases_not_source_shaped_text(
    tmp_path: Path,
) -> None:
    _write_results(
        tmp_path / "TEST-suite.xml",
        """
<testcase classname="example.One" name="first" />
<testcase classname="example.One" name="second"><skipped /></testcase>
<system-out>@Test inside diagnostics is not a test result</system-out>
""",
        tests=2,
        skipped=1,
    )

    summary = qualification.read_test_results(tmp_path)

    assert summary == qualification.TestResultSummary(
        tests=2,
        skipped=1,
        files=1,
    )


def test_junit_results_fail_closed_on_duplicate_and_malformed_evidence(
    tmp_path: Path,
) -> None:
    testcase = '<testcase classname="example.One" name="same" />'
    _write_results(tmp_path / "one" / "TEST-one.xml", testcase, tests=1)
    _write_results(tmp_path / "two" / "TEST-two.xml", testcase, tests=1)
    with pytest.raises(qualification.EvidenceError, match="duplicate test case"):
        qualification.read_test_results(tmp_path)

    malformed = tmp_path / "malformed"
    _write_results(
        malformed / "TEST-malformed.xml",
        '<testcase classname="example.One" name="only" />',
        tests=2,
    )
    with pytest.raises(qualification.EvidenceError, match="summary mismatch"):
        qualification.read_test_results(malformed)

    hidden_failure = tmp_path / "hidden-failure"
    _write_results(
        hidden_failure / "TEST-hidden.xml",
        '<testcase classname="example.One" name="only" />',
        tests=1,
        failures=1,
    )
    with pytest.raises(qualification.EvidenceError, match="summary mismatch"):
        qualification.read_test_results(hidden_failure)

    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "TEST-nested.xml").write_text(
        """
<testsuites tests="1" failures="0" errors="0" skipped="0">
  <testsuite name="aggregate" tests="2" failures="0" errors="0" skipped="0">
    <testsuite name="leaf" tests="1" failures="0" errors="0" skipped="0">
      <testcase classname="example.One" name="only" />
    </testsuite>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )
    with pytest.raises(qualification.EvidenceError, match="summary mismatch"):
        qualification.read_test_results(nested)


def test_result_qualification_uses_each_lane_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("jvm=2\ninstrumentation=1\n", encoding="utf-8")
    results = tmp_path / "results"
    _write_results(
        results / "TEST-suite.xml",
        """
<testcase classname="example.One" name="first" />
<testcase classname="example.One" name="second" />
""",
        tests=2,
    )

    assert qualification.verify_test_results(
        lane="jvm",
        baseline_path=baseline,
        results_dir=results,
    ).tests == 2
    with pytest.raises(qualification.EvidenceError, match="actual=2, baseline=1"):
        qualification.verify_test_results(
            lane="instrumentation",
            baseline_path=baseline,
            results_dir=results,
        )


def test_legacy_scalar_is_only_accepted_for_base_ratchet_migration() -> None:
    with pytest.raises(qualification.EvidenceError, match="malformed"):
        qualification.parse_test_baseline("1589\n", "current")

    assert qualification.parse_test_baseline(
        "1589\n",
        "base",
        legacy_scalar_lane="jvm",
    ) == {
        "jvm": 1589,
        "instrumentation": 0,
    }


def test_apkanalyzer_launch_failure_is_evidence_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_launch(*_args: object, **_kwargs: object) -> None:
        raise OSError("missing executable")

    monkeypatch.setattr(qualification.subprocess, "run", reject_launch)

    with pytest.raises(qualification.EvidenceError, match="Could not run apkanalyzer"):
        qualification._run_apkanalyzer(Path("apkanalyzer"), "manifest", "print")

    observed: dict[str, object] = {}

    def successful_run(*_args: object, **kwargs: object) -> object:
        observed.update(kwargs)
        return qualification.subprocess.CompletedProcess(
            args=["apkanalyzer"],
            returncode=0,
            stdout="<manifest />",
            stderr="",
        )

    monkeypatch.setattr(qualification.subprocess, "run", successful_run)
    assert (
        qualification._run_apkanalyzer(
            Path("apkanalyzer"),
            "manifest",
            "print",
        )
        == "<manifest />"
    )
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "strict"


def test_cli_returns_failure_when_runtime_qualification_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def reject_results(**_kwargs: object) -> None:
        raise qualification.EvidenceError("runtime result rejected")

    monkeypatch.setattr(qualification, "verify_test_results", reject_results)

    assert qualification.main(
        [
            "results",
            "--lane",
            "jvm",
            "--baseline",
            "baseline.txt",
            "--results-dir",
            "results",
        ]
    ) == 1
    assert "runtime result rejected" in capsys.readouterr().err


def test_connected_cli_qualifies_results_and_process_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        qualification,
        "verify_test_results",
        lambda **_kwargs: qualification.TestResultSummary(49, 0, 1),
    )
    monkeypatch.setattr(
        qualification,
        "verify_process_health",
        lambda **_kwargs: 1,
    )

    assert qualification.main(
        [
            "connected",
            "--baseline",
            "baseline.txt",
            "--results-dir",
            "results",
            "--before",
            "before.txt",
            "--after",
            "after.txt",
            "--apkanalyzer",
            "apkanalyzer",
            "--apk-output-dir",
            "app-apk",
            "--apk-output-dir",
            "test-apk",
        ]
    ) == 0
    assert "49 tests" in capsys.readouterr().out
