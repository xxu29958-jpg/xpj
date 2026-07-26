from __future__ import annotations

from pathlib import Path

import pytest

from tests._infra.android_test_qualification import qualification


def _snapshot(records: str) -> str:
    return f"""
===== Android target emulator-5554 =====
ACTIVITY MANAGER PROCESS EXIT INFO (dumpsys activity exit-info)
 package: com.ticketbox
  Historical Process Exit for uid=10123
{records}
"""


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

    failures = qualification.new_unhealthy_exits(
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

    assert qualification.new_unhealthy_exits(before, after, {"com.ticketbox"}) == []
    with pytest.raises(qualification.EvidenceError, match="no new target"):
        qualification.require_expected_process_exit(
            qualification.new_exit_records(before, after),
            {"com.ticketbox"},
        )


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        (0, 0),
        (1, 1),
        (2, 9),
        (3, 0),
        (4, 0),
        (5, 11),
        (6, 0),
        (7, 0),
        (9, 0),
        (12, 0),
        (17, 0),
        (99, 0),
    ],
)
def test_each_unhealthy_or_unknown_exit_is_rejected(
    reason: int,
    status: int,
) -> None:
    before = qualification.parse_exit_snapshot(_snapshot(""))
    after = qualification.parse_exit_snapshot(
        _snapshot(_new_record(reason=reason, status=status))
    )

    failures = qualification.new_unhealthy_exits(
        before,
        after,
        {"com.ticketbox"},
    )

    assert [record.reason for record in failures] == [reason]


@pytest.mark.parametrize("reason", [1, 10, 15, 16])
def test_expected_process_exit_accepts_only_normal_status(reason: int) -> None:
    before = qualification.parse_exit_snapshot(_snapshot(""))
    after = qualification.parse_exit_snapshot(
        _snapshot(
            _new_record(process="com.ticketbox", reason=reason, status=0)
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
    assert qualification.new_unhealthy_exits(before, after, {"com.ticketbox"}) == []


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
