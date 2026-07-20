from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_atomic_promise_commit_counter_ignores_nested_functions() -> None:
    mod = importlib.reload(importlib.import_module("_audit_atomic_promise_vs_commits"))
    tree = ast.parse(
        '''
def outer(db):
    """atomic write."""
    db.commit()
    def nested():
        db.commit()
    return nested
'''
    )
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)

    assert mod._commit_count(function) == 1


def test_allowlist_reason_placeholder_check_uses_word_boundaries() -> None:
    mod = importlib.reload(importlib.import_module("_audit_allowlist_reasons"))

    assert mod._reason_uses_placeholder("tracker is unknown")
    assert not mod._reason_uses_placeholder("tracker is wiped on unknown-host responses")
    assert not mod._reason_uses_placeholder("known upstream route keeps laterally safe ownership")


def test_allowlist_reason_scope_claims_are_machine_checked() -> None:
    mod = importlib.reload(importlib.import_module("_audit_allowlist_reasons"))

    assert mod._scope_claim_failure(
        "POST /api/ledgers/{ledger_id}/members/{member_id}/role",
        "owner-console-only - role assignment",
    )
    assert mod._scope_claim_failure(
        "POST /web/budgets/save",
        "single-writer monthly budget",
    )
    assert mod._scope_claim_failure(
        "POST /api/admin/devices/{public_id}/rename",
        "owner-only - device rename under admin API",
    ) is None
    assert mod._scope_claim_failure(
        "POST /owner/upload-links/{public_id}/limits",
        "owner-console-only - single-writer rate-limit edit",
    ) is None


def test_release_audit_compact_mode_suppresses_success_noise(monkeypatch, capsys) -> None:
    mod = importlib.reload(importlib.import_module("release_audit"))
    calls: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="noisy success details\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod._run_lane("sample", "_audit_sample.py", SCRIPTS, compact=True)

    captured = capsys.readouterr()
    assert "PASS  sample" in captured.out
    assert "noisy success details" not in captured.out
    assert calls[0]["capture_output"] is True


def test_release_audit_discovers_adr_contract_lane() -> None:
    mod = importlib.reload(importlib.import_module("release_audit"))

    lanes = set(mod._discover_lanes(SCRIPTS))

    assert ("adr-contracts", "_audit_adr_contracts.py") in lanes
    assert ("adr-registry", "_audit_adr_registry.py") not in lanes


def test_adr_contract_gate_is_present_in_a_clean_git_clone() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "backend/scripts/_audit_adr_contracts.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_release_audit_compact_mode_prints_failure_output(monkeypatch, capsys) -> None:
    mod = importlib.reload(importlib.import_module("release_audit"))

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="failure detail\n", stderr="stderr detail\n")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert not mod._run_lane("sample", "_audit_sample.py", SCRIPTS, compact=True)

    captured = capsys.readouterr()
    assert "FAIL  sample" in captured.out
    assert "failure detail" in captured.out
    assert "stderr detail" in captured.err


def test_pr_delta_accepts_adr_0049_exact_down_ratchet_exception(monkeypatch) -> None:
    # The single in-flight grandfather now points at the desktop two-phase
    # credential activation exemption (PR #219). Older up-hops are dead history.
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    baseline = dict(mod.STRICT_EQUALITY_BASELINE)
    baseline["mutate_token_exempted"] = 123
    monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", baseline)

    _bootstrapped, violations, _removed = mod._compute_ratchet_findings(
        {"mutate_token_exempted": 122}
    )

    assert violations == []


def test_pr_delta_adr_0049_exception_does_not_allow_future_growth(monkeypatch) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))

    # Non-grandfathered transitions still fail: the 122 -> 123 exception is exact, so
    # older up-hops, dead hops, and overshoots are never waved through.
    for base_count, current_count in ((116, 119), (119, 120), (120, 121), (121, 122), (121, 123), (122, 124)):
        baseline = dict(mod.STRICT_EQUALITY_BASELINE)
        baseline["mutate_token_exempted"] = current_count
        monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", baseline)
        _bootstrapped, violations, _removed = mod._compute_ratchet_findings(
            {"mutate_token_exempted": base_count}
        )

        assert len(violations) == 1
        assert str(base_count) in violations[0]
        assert str(current_count) in violations[0]


def test_pr_delta_flags_missing_extra_and_unreadable_base_in_pr_ci(
    monkeypatch,
    capsys,
) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", {"backend_pytest_count": 2403})
    monkeypatch.setenv("XPJ_AUDIT_BASE_REF", "0123456789abcdef")
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    assert mod._strict_baseline_git_ref() is None
    assert "cannot resolve exact ADR ratchet base" in (mod._strict_baseline_selection_error or "")
    monkeypatch.setattr(mod, "_read_base_strict_baseline", lambda: (False, {}))
    assert mod.evaluate_pr_delta_metrics({"backend_pytest_count": 2403}) == 1
    exact_ref_only = capsys.readouterr()
    assert "couldn't read the required base baseline" in exact_ref_only.out
    assert "XPJ_AUDIT_BASE_REF=0123456789abcdef" in exact_ref_only.out

    monkeypatch.delenv("XPJ_AUDIT_BASE_REF")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    assert mod._strict_baseline_git_ref() is None
    assert mod._strict_baseline_selection_error == (
        "CI requires XPJ_AUDIT_BASE_REF with the exact pre-change commit"
    )

    assert mod.evaluate_pr_delta_metrics({"unexpected_counter": 1}) == 1

    captured = capsys.readouterr()
    assert "baseline entries that the audit lane didn't report" in captured.out
    assert "audit reported counters with no baseline entry" in captured.out
    assert "couldn't read the required base baseline" in captured.out
    assert "GITHUB_BASE_REF=main" in captured.out


def test_pr_delta_flags_extra_and_unreadable_base_independently(
    monkeypatch,
    capsys,
) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    baseline = {"backend_pytest_count": 2403}
    monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", baseline)
    monkeypatch.setattr(mod, "_read_base_strict_baseline", lambda: (True, baseline))

    assert mod.evaluate_pr_delta_metrics({
        "backend_pytest_count": 2403,
        "unexpected_counter": 1,
    }) == 1

    extra_only = capsys.readouterr()
    assert "audit reported counters with no baseline entry" in extra_only.out
    assert "baseline entries that the audit lane didn't report" not in extra_only.out
    assert "couldn't read the required base baseline" not in extra_only.out

    monkeypatch.setattr(mod, "_read_base_strict_baseline", lambda: (False, {}))
    monkeypatch.setenv("GITHUB_BASE_REF", "main")

    assert mod.evaluate_pr_delta_metrics({"backend_pytest_count": 2403}) == 1

    unreadable_only = capsys.readouterr()
    assert "couldn't read the required base baseline" in unreadable_only.out
    assert "GITHUB_BASE_REF=main" in unreadable_only.out
    assert "audit reported counters with no baseline entry" not in unreadable_only.out
    assert "baseline entries that the audit lane didn't report" not in unreadable_only.out

    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.delenv("XPJ_AUDIT_BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    for marker in ("CI", "GITHUB_ACTIONS", "GITEA_ACTIONS"):
        for candidate in ("CI", "GITHUB_ACTIONS", "GITEA_ACTIONS"):
            monkeypatch.delenv(candidate, raising=False)
        monkeypatch.setenv(marker, "true")
        assert mod.evaluate_pr_delta_metrics({"backend_pytest_count": 2403}) == 1
        marker_output = capsys.readouterr()
        assert "couldn't read the required base baseline" in marker_output.out

    for marker in ("CI", "GITHUB_ACTIONS", "GITEA_ACTIONS"):
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("CI", "false")
    assert mod.evaluate_pr_delta_metrics({"backend_pytest_count": 2403}) == 1
    noncanonical_marker = capsys.readouterr()
    assert "couldn't read the required base baseline" in noncanonical_marker.out
    monkeypatch.delenv("CI")

    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert mod.evaluate_pr_delta_metrics({"backend_pytest_count": 2403}) == 1
    event_only = capsys.readouterr()
    assert "couldn't read the required base baseline" in event_only.out
    monkeypatch.delenv("GITHUB_EVENT_NAME")

    assert mod.evaluate_pr_delta_metrics({"backend_pytest_count": 2403}) == 0
    local_only = capsys.readouterr()
    assert "no CI/exact-base context" in local_only.out


def test_mutate_token_ledger_is_consistent_with_live_tables() -> None:
    import app.main  # noqa: F401 — importing the app registers every model on Base.metadata
    from app.database import Base

    ledger = importlib.reload(importlib.import_module("_mutate_token_ledger"))
    real_tables = set(Base.metadata.tables.keys())

    # Every touched_tables name is a real table, every reason_code/owner/risk
    # is in vocabulary, and the empty-iff-no-write rule holds for all entries.
    assert ledger.validate_ledger(real_tables) == []
    # Risk tiers are still in the future, so the review gate is not overdue.
    assert ledger.review_overdue() == []


def test_mutate_token_ledger_rejects_inconsistent_entries() -> None:
    ledger = importlib.reload(importlib.import_module("_mutate_token_ledger"))
    exempt = ledger.Exempt
    real_tables = {"goals", "expenses"}
    bad_entries = {
        "POST /x/unknown-table": exempt("create_row", "goals", ("no_such_table",)),
        "POST /x/read-only-but-writes": exempt("read_only_compute", "goals", ("goals",)),
        "POST /x/write-code-no-tables": exempt("batch_db_write", "goals", ()),
        "POST /web/owner-console-elsewhere": exempt("create_row", "owner_console", ("goals",)),
    }
    joined = " | ".join(ledger.validate_entries(bad_entries, real_tables))

    assert "unknown table 'no_such_table'" in joined
    assert "must be empty" in joined  # read_only_compute may not declare tables
    assert "must list >=1 table" in joined  # a writing reason_code must
    assert "only valid for /owner routes" in joined


def test_mutate_token_ledger_review_overdue_fires_after_deadline() -> None:
    from datetime import date

    ledger = importlib.reload(importlib.import_module("_mutate_token_ledger"))
    overdue = ledger.review_overdue(date(2099, 1, 1))

    assert len(overdue) == len(ledger.RISK_REVIEW_BY)


def test_route_pair_web_coverage_is_complete_and_gated() -> None:
    mod = importlib.reload(importlib.import_module("_audit_route_pair_consistency"))
    routes = mod._routes_by_key()

    # Live tree: every /web mutation either shares a service op with /api,
    # is a precise pair, or is explicitly web-only.
    failures, _info = mod._check_web_coverage(routes)
    assert failures == []

    # Emptying the opt-out must surface the genuinely web-only routes as
    # drift — proving the coverage check actually depends on classification.
    original = mod.WEB_ONLY_ROUTES
    mod.WEB_ONLY_ROUTES = {}
    try:
        failures_without_optout, _ = mod._check_web_coverage(routes)
    finally:
        mod.WEB_ONLY_ROUTES = original
    assert len(failures_without_optout) == len(original)


def test_outbox_dispatcher_coverage_holds_on_live_tree() -> None:
    mod = importlib.reload(importlib.import_module("_audit_android_outbox_dispatcher_coverage"))
    files = mod._kt_files(mod.ANDROID_SRC)
    enum_types = mod.parse_enum_types(mod._read(mod.TYPE_FILE))
    dispatcher_map = mod.parse_dispatchers(files)
    registered = mod.parse_registered_classes(mod._read(mod.APP_CONTAINER))
    enqueue_types = mod.parse_enqueues(files, enum_types)

    # Parsers actually found the live wiring (guards against a silent parse break).
    assert "Unknown" in enum_types and len(enum_types) > 5
    assert dispatcher_map
    assert set(dispatcher_map.values()) <= registered  # every dispatcher class registered

    assert (
        mod.evaluate(
            enum_types=enum_types,
            dispatcher_map=dispatcher_map,
            registered_classes=registered,
            enqueue_types=enqueue_types,
            allowlist_no_callsite=mod.DISPATCHER_WITHOUT_CALLSITE,
        )
        == []
    )


def test_outbox_dispatcher_registry_parser_ignores_non_outbox_dispatchers() -> None:
    mod = importlib.reload(importlib.import_module("_audit_android_outbox_dispatcher_coverage"))
    source = """
class AppContainer {
    private val outboxDispatchers: List<OutboxMutationDispatcher> = listOf(
        PatchExpenseDispatcher(
            apiProvider = { api },
        ),
    )

    val recurringReminderEngine = RecurringReminderEngine(
        dispatcher = NotifierRecurringReminderDispatcher(notifier::onRecurringDue),
    )
}
"""

    assert mod.parse_registered_classes(source) == {"PatchExpenseDispatcher"}


def test_outbox_dispatcher_coverage_flags_three_way_drift() -> None:
    mod = importlib.reload(importlib.import_module("_audit_android_outbox_dispatcher_coverage"))
    # PatchExpense: enqueued but has no dispatcher -> rows drain to FAILED.
    # RejectExpense: dispatcher exists but is not registered in AppContainer.
    # UpdateGoal: registered dispatcher with no enqueue call site (dead wiring).
    # Unknown: must never be enqueued.
    problems = mod.evaluate(
        enum_types={"PatchExpense", "RejectExpense", "UpdateGoal", "Unknown"},
        dispatcher_map={"RejectExpense": "RejectExpenseDispatcher", "UpdateGoal": "UpdateGoalDispatcher"},
        registered_classes={"UpdateGoalDispatcher"},
        enqueue_types={"PatchExpense": {"X.kt"}, "Unknown": {"Y.kt"}},
        allowlist_no_callsite=frozenset(),
    )
    joined = " | ".join(problems)
    assert "PatchExpense is enqueued" in joined and "no dispatcher" in joined
    assert "RejectExpenseDispatcher" in joined and "not registered" in joined
    assert "UpdateGoal" in joined and "dead wiring" in joined
    assert "Unknown must never be enqueued" in joined
