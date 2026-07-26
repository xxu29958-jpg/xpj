from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPOSITORY_ROOT / "android" / "scripts" / "verify_connected_process_health.py"
)


def _load_script() -> object:
    spec = importlib.util.spec_from_file_location(
        "_test_android_connected_process_health",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


process_health = _load_script()


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
    snapshot = process_health.parse_exit_snapshot(
        _snapshot(_old_record() + _new_record(pid=456))
    )

    assert snapshot.targets == {"emulator-5554"}
    assert [(record.pid, record.reason) for record in snapshot.records] == [
        (123, 4),
        (456, 5),
    ]


def test_new_native_crash_is_a_failure() -> None:
    before = process_health.parse_exit_snapshot(_snapshot(""))
    after = process_health.parse_exit_snapshot(_snapshot(_new_record()))

    failures = process_health.new_fatal_exits(
        before,
        after,
        {"com.ticketbox"},
    )

    assert [(record.process, record.reason) for record in failures] == [
        ("com.ticketbox", 5)
    ]


def test_stale_crash_from_before_the_run_is_ignored() -> None:
    evidence = _snapshot(_old_record())
    before = process_health.parse_exit_snapshot(evidence)
    after = process_health.parse_exit_snapshot(evidence)

    assert process_health.new_fatal_exits(before, after, {"com.ticketbox"}) == []
    with pytest.raises(process_health.EvidenceError, match="no new target"):
        process_health.require_expected_process_exit(
            process_health.new_exit_records(before, after),
            {"com.ticketbox"},
        )


@pytest.mark.parametrize("reason", [4, 5, 6, 7])
def test_each_android_fatal_exit_reason_is_rejected(reason: int) -> None:
    before = process_health.parse_exit_snapshot(_snapshot(""))
    after = process_health.parse_exit_snapshot(
        _snapshot(_new_record(reason=reason))
    )

    failures = process_health.new_fatal_exits(
        before,
        after,
        {"com.ticketbox"},
    )

    assert [record.reason for record in failures] == [reason]


def test_unrelated_process_exit_is_ignored() -> None:
    before = process_health.parse_exit_snapshot(_snapshot(""))
    after = process_health.parse_exit_snapshot(
        _snapshot(
            _new_record(process="com.ticketbox", reason=10, status=0)
            + _new_record(process="com.android.systemui", pid=456)
        )
    )

    assert (
        process_health.require_expected_process_exit(
            process_health.new_exit_records(before, after),
            {"com.ticketbox"},
        )
        == 1
    )
    assert process_health.new_fatal_exits(before, after, {"com.ticketbox"}) == []


def test_exit_snapshot_fails_closed_on_malformed_evidence() -> None:
    with pytest.raises(process_health.EvidenceError, match="missing status"):
        process_health.parse_exit_snapshot(
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
    with pytest.raises(process_health.EvidenceError, match="header is malformed"):
        process_health.parse_exit_snapshot(_snapshot(malformed_header))


def test_manifest_processes_are_derived_without_hardcoded_package_names() -> None:
    manifest = """
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <application>
    <service android:process=":sync" />
    <provider android:process="shared.worker" />
  </application>
</manifest>
"""

    assert process_health.application_processes("family.finance", manifest) == {
        "family.finance",
        "family.finance:sync",
        "shared.worker",
    }
