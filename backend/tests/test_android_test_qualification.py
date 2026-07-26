from __future__ import annotations

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
