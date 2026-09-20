from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests._infra.android_test_qualification import qualification


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


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_junit_results_parse_reported_cases_not_source_shaped_text(
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


def test_result_qualification_rejects_skipped_cases(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("jvm=2\ninstrumentation=1\n", encoding="utf-8")
    results = tmp_path / "results"
    _write_results(
        results / "TEST-suite.xml",
        """
<testcase classname="example.One" name="first" />
<testcase classname="example.One" name="second"><skipped /></testcase>
""",
        tests=2,
        skipped=1,
    )

    with pytest.raises(qualification.EvidenceError, match="skipped=1"):
        qualification.verify_test_results(
            lane="jvm",
            baseline_path=baseline,
            results_dir=results,
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

    assert (
        qualification.verify_test_results(
            lane="jvm",
            baseline_path=baseline,
            results_dir=results,
        ).tests
        == 2
    )
    assert (
        qualification.verify_test_results(
            lane="instrumentation",
            baseline_path=baseline,
            results_dir=results,
        ).tests
        == 2
    )

    baseline.write_text("jvm=3\ninstrumentation=1\n", encoding="utf-8")
    with pytest.raises(qualification.EvidenceError, match="actual=2, minimum=3"):
        qualification.verify_test_results(
            lane="jvm",
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


def test_baseline_ratchet_prefers_exact_audit_sha_over_branch_name(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "Android qualification test")
    _git(repository, "config", "user.email", "qualification@example.invalid")
    baseline = repository / "android" / "audit" / "test_count_baseline.txt"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("jvm=1\ninstrumentation=1\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "base")
    base_sha = _git(repository, "rev-parse", "HEAD")

    baseline.write_text("jvm=2\ninstrumentation=2\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "head")
    head_sha = _git(repository, "rev-parse", "HEAD")

    current, base, selected_ref = qualification.verify_baseline_ratchet(
        baseline_path=baseline,
        repository_root=repository,
        environment={
            "CI": "true",
            "GITHUB_BASE_REF": "main",
            "XPJ_AUDIT_BASE_REF": base_sha,
        },
    )

    assert current == {"jvm": 2, "instrumentation": 2}
    assert base == {"jvm": 1, "instrumentation": 1}
    assert selected_ref == base_sha

    with pytest.raises(qualification.EvidenceError, match="self-comparison"):
        qualification.verify_baseline_ratchet(
            baseline_path=baseline,
            repository_root=repository,
            environment={
                "CI": "true",
                "XPJ_AUDIT_BASE_REF": head_sha,
            },
        )

    sibling_sha = _git(
        repository,
        "commit-tree",
        f"{base_sha}^{{tree}}",
        "-p",
        base_sha,
        "-m",
        "sibling",
    )
    with pytest.raises(qualification.EvidenceError, match="must be an ancestor"):
        qualification.verify_baseline_ratchet(
            baseline_path=baseline,
            repository_root=repository,
            environment={"CI": "true", "XPJ_AUDIT_BASE_REF": sibling_sha},
        )


def test_baseline_ratchet_rejects_an_unreachable_explicit_sha(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    baseline = repository / "android" / "audit" / "test_count_baseline.txt"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("jvm=1\ninstrumentation=1\n", encoding="utf-8")

    with pytest.raises(qualification.EvidenceError, match="is unreachable"):
        qualification.verify_baseline_ratchet(
            baseline_path=baseline,
            repository_root=repository,
            environment={
                "CI": "true",
                "GITHUB_EVENT_NAME": "push",
                "XPJ_AUDIT_BASE_REF": "f" * 40,
            },
        )


def test_baseline_ratchet_requires_an_exact_ref_in_ci(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    baseline = repository / "android" / "audit" / "test_count_baseline.txt"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("jvm=1\ninstrumentation=1\n", encoding="utf-8")

    with pytest.raises(
        qualification.EvidenceError,
        match="CI requires XPJ_AUDIT_BASE_REF",
    ):
        qualification.verify_baseline_ratchet(
            baseline_path=baseline,
            repository_root=repository,
            environment={"CI": "true", "GITHUB_EVENT_NAME": "push"},
        )


def test_cli_returns_failure_when_runtime_qualification_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def reject_results(**_kwargs: object) -> None:
        raise qualification.EvidenceError("runtime result rejected")

    monkeypatch.setattr(qualification, "verify_test_results", reject_results)

    assert (
        qualification.main(
            [
                "results",
                "--lane",
                "jvm",
                "--baseline",
                "baseline.txt",
                "--results-dir",
                "results",
            ]
        )
        == 1
    )
    assert "runtime result rejected" in capsys.readouterr().err


def _discovery_output(identities: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    total = len(identities)
    for current, (class_name, test_name) in enumerate(identities, start=1):
        for status_code in (1, 0):
            lines.extend(
                [
                    f"INSTRUMENTATION_STATUS: class={class_name}",
                    f"INSTRUMENTATION_STATUS: current={current}",
                    "INSTRUMENTATION_STATUS: id=AndroidJUnitRunner",
                    f"INSTRUMENTATION_STATUS: numtests={total}",
                    f"INSTRUMENTATION_STATUS: test={test_name}",
                    f"INSTRUMENTATION_STATUS_CODE: {status_code}",
                ]
            )
    lines.extend(
        [
            "INSTRUMENTATION_RESULT: stream=",
            f"OK ({total} tests)",
            "INSTRUMENTATION_CODE: -1",
        ]
    )
    return "\n".join(lines)


def test_runtime_discovery_preserves_complete_parameterized_identities() -> None:
    identities = [
        (
            "example.UploadIntentCleanupTest",
            f"deletionReclaims[{entry}]",
        )
        for entry in ("CLEAR_ALL", "FAILED_DROP", "STOP")
    ]

    discovery = qualification.parse_runtime_discovery(
        _discovery_output(identities),
        process_exit_code=0,
    )

    assert discovery.identities == tuple(identities)
    assert discovery.reported_tests == len(identities)


@pytest.mark.parametrize(
    ("text", "process_exit_code", "message"),
    [
        (
            "INSTRUMENTATION_RESULT: stream=\nOK (0 tests)\nINSTRUMENTATION_CODE: -1\n",
            0,
            "no tests",
        ),
        (
            "\n".join(
                [
                    "INSTRUMENTATION_STATUS: class=example.Missing",
                    "INSTRUMENTATION_STATUS: current=1",
                    "INSTRUMENTATION_STATUS: numtests=1",
                    "INSTRUMENTATION_STATUS: test=initializationError",
                    "INSTRUMENTATION_STATUS_CODE: -2",
                    "FAILURES!!!",
                    "INSTRUMENTATION_CODE: -1",
                ]
            ),
            0,
            "status code -2",
        ),
        (
            "INSTRUMENTATION_FAILED: example.test/example.MissingRunner\n",
            1,
            "exit code 1",
        ),
    ],
)
def test_runtime_discovery_rejects_empty_and_runner_failures(
    text: str,
    process_exit_code: int,
    message: str,
) -> None:
    with pytest.raises(qualification.EvidenceError, match=message):
        qualification.parse_runtime_discovery(
            text,
            process_exit_code=process_exit_code,
        )


def test_local_shard_evidence_preserves_xml_and_discovery_ids(tmp_path: Path) -> None:
    results = tmp_path / "results"
    identity = ("example.Parameterized", "journey[variant A]")
    _write_results(
        results / "TEST-shard.xml",
        f'<testcase classname="{identity[0]}" name="{identity[1]}" />',
        tests=1,
    )
    discovery_output = tmp_path / "discovery.txt"
    discovery_output.write_text(_discovery_output([identity]), encoding="utf-8")
    discovery_exit = tmp_path / "discovery-exit.txt"
    discovery_exit.write_text("0\n", encoding="utf-8")
    output = tmp_path / "ticketbox-connected-shard-evidence.json"

    summary = qualification.write_connected_shard_evidence(
        results_dir=results,
        discovery_output=discovery_output,
        discovery_exit_code_file=discovery_exit,
        process_exit_records=1,
        output_path=output,
        checkout_sha="a" * 40,
        source_sha="b" * 40,
        run_id="12345",
        run_attempt=1,
        shard_index=0,
        shard_count=2,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert summary.tests == 1
    assert payload["discovery_ids"] == [list(identity)]
    assert payload["executed_ids"] == [list(identity)]


def _write_shard_evidence(
    root: Path,
    *,
    artifact: str,
    shard_index: int,
    identities: list[tuple[str, str]],
    discovery: list[tuple[str, str]],
    checkout_sha: str = "a" * 40,
    source_sha: str = "b" * 40,
    shard_count: int = 2,
    run_attempt: int = 1,
) -> None:
    destination = root / artifact / "ticketbox-connected-shard-evidence.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "schema": "ticketbox-connected-shard-evidence/v1",
                "checkout_sha": checkout_sha,
                "source_sha": source_sha,
                "run_id": "12345",
                "run_attempt": run_attempt,
                "shard_index": shard_index,
                "shard_count": shard_count,
                "discovery_ids": [list(identity) for identity in discovery],
                "executed_ids": [list(identity) for identity in identities],
                "process_exit_records": 1,
            }
        ),
        encoding="utf-8",
    )


def test_connected_shards_require_exact_runtime_inventory_union(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("jvm=1\ninstrumentation=3\n", encoding="utf-8")
    identities = [
        ("example.One", "first"),
        ("example.One", "parameterized[A]"),
        ("example.One", "parameterized[B]"),
    ]
    evidence = tmp_path / "evidence"
    _write_shard_evidence(
        evidence,
        artifact="shard-0",
        shard_index=0,
        identities=identities[:2],
        discovery=identities,
    )
    _write_shard_evidence(
        evidence,
        artifact="shard-1",
        shard_index=1,
        identities=identities[2:],
        discovery=identities,
    )

    summary = qualification.verify_connected_shards(
        evidence_root=evidence,
        baseline_path=baseline,
        expected_shard_count=2,
        expected_checkout_sha="a" * 40,
        expected_source_sha="b" * 40,
        expected_run_id="12345",
        expected_run_attempt=1,
    )

    assert summary.tests == 3


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_shard",
        "duplicate_coordinate",
        "empty_shard",
        "wrong_checkout",
        "wrong_count",
        "different_inventory",
        "duplicate_execution",
    ],
)
def test_connected_shards_fail_closed_on_partition_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("jvm=1\ninstrumentation=2\n", encoding="utf-8")
    identities = [("example.One", "first"), ("example.One", "second")]
    evidence = tmp_path / "evidence"
    _write_shard_evidence(
        evidence,
        artifact="shard-0",
        shard_index=0,
        identities=[] if mutation == "empty_shard" else identities[:1],
        discovery=identities,
        checkout_sha="c" * 40 if mutation == "wrong_checkout" else "a" * 40,
        shard_count=3 if mutation == "wrong_count" else 2,
    )
    if mutation != "missing_shard":
        _write_shard_evidence(
            evidence,
            artifact="shard-1",
            shard_index=0 if mutation == "duplicate_coordinate" else 1,
            identities=(identities if mutation == "duplicate_execution" else identities[1:]),
            discovery=(identities[:1] if mutation == "different_inventory" else identities),
        )

    with pytest.raises(qualification.EvidenceError):
        qualification.verify_connected_shards(
            evidence_root=evidence,
            baseline_path=baseline,
            expected_shard_count=2,
            expected_checkout_sha="a" * 40,
            expected_source_sha="b" * 40,
            expected_run_id="12345",
            expected_run_attempt=1,
        )


def test_connected_shards_apply_the_unsplit_global_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("jvm=1\ninstrumentation=3\n", encoding="utf-8")
    identities = [("example.One", "first"), ("example.One", "second")]
    evidence = tmp_path / "evidence"
    for index, identity in enumerate(identities):
        _write_shard_evidence(
            evidence,
            artifact=f"shard-{index}",
            shard_index=index,
            identities=[identity],
            discovery=identities,
        )

    with pytest.raises(qualification.EvidenceError, match="minimum=3"):
        qualification.verify_connected_shards(
            evidence_root=evidence,
            baseline_path=baseline,
            expected_shard_count=2,
            expected_checkout_sha="a" * 40,
            expected_source_sha="b" * 40,
            expected_run_id="12345",
            expected_run_attempt=1,
        )


def test_connected_shards_accept_latest_success_from_each_failed_job_rerun_attempt(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("jvm=1\ninstrumentation=2\n", encoding="utf-8")
    identities = [("example.One", "first"), ("example.One", "second")]
    evidence = tmp_path / "evidence"
    _write_shard_evidence(
        evidence,
        artifact="connected-shard-0-attempt-1",
        shard_index=0,
        identities=identities[:1],
        discovery=identities,
        run_attempt=1,
    )
    _write_shard_evidence(
        evidence,
        artifact="connected-shard-1-attempt-1",
        shard_index=1,
        identities=identities[1:],
        discovery=identities,
        run_attempt=1,
    )
    _write_shard_evidence(
        evidence,
        artifact="connected-shard-1-attempt-2",
        shard_index=1,
        identities=identities[1:],
        discovery=identities,
        run_attempt=2,
    )

    summary = qualification.verify_connected_shards(
        evidence_root=evidence,
        baseline_path=baseline,
        expected_shard_count=2,
        expected_checkout_sha="a" * 40,
        expected_source_sha="b" * 40,
        expected_run_id="12345",
        expected_run_attempt=2,
    )

    assert summary.tests == 2


def test_connected_shard_rejects_zero_sha_pseudo_identity(tmp_path: Path) -> None:
    results = tmp_path / "results"
    identity = ("example.One", "first")
    _write_results(
        results / "TEST-shard.xml",
        f'<testcase classname="{identity[0]}" name="{identity[1]}" />',
        tests=1,
    )
    discovery_output = tmp_path / "discovery.txt"
    discovery_output.write_text(_discovery_output([identity]), encoding="utf-8")
    discovery_exit = tmp_path / "discovery-exit.txt"
    discovery_exit.write_text("0\n", encoding="utf-8")

    with pytest.raises(qualification.EvidenceError, match="full Git SHA"):
        qualification.write_connected_shard_evidence(
            results_dir=results,
            discovery_output=discovery_output,
            discovery_exit_code_file=discovery_exit,
            process_exit_records=1,
            output_path=tmp_path / "evidence.json",
            checkout_sha="0" * 40,
            source_sha="b" * 40,
            run_id="12345",
            run_attempt=1,
            shard_index=0,
            shard_count=2,
        )


def test_connected_shards_reject_future_attempt_evidence(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("jvm=1\ninstrumentation=2\n", encoding="utf-8")
    identities = [("example.One", "first"), ("example.One", "second")]
    evidence = tmp_path / "evidence"
    for index, identity in enumerate(identities):
        _write_shard_evidence(
            evidence,
            artifact=f"connected-shard-{index}-attempt-3",
            shard_index=index,
            identities=[identity],
            discovery=identities,
            run_attempt=3,
        )

    with pytest.raises(qualification.EvidenceError, match="attempt"):
        qualification.verify_connected_shards(
            evidence_root=evidence,
            baseline_path=baseline,
            expected_shard_count=2,
            expected_checkout_sha="a" * 40,
            expected_source_sha="b" * 40,
            expected_run_id="12345",
            expected_run_attempt=2,
        )
