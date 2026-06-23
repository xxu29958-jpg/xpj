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
    # issue #65 slice 6a re-points the single in-flight grandfather to 116 -> 119
    # (+3 owner "My Devices" mutating routes). The prior 115 -> 116 hop is dead
    # history — main sits at 116, so no future pr-delta has base 115.
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    baseline = dict(mod.STRICT_EQUALITY_BASELINE)
    baseline["mutate_token_exempted"] = 119
    monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", baseline)

    _bootstrapped, violations, _removed = mod._compute_ratchet_findings(
        {"mutate_token_exempted": 116}
    )

    assert violations == []


def test_pr_delta_adr_0049_exception_does_not_allow_future_growth(monkeypatch) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))

    # Non-grandfathered transitions still fail: the 116 -> 119 exception is exact, so
    # neither a different hop (115 -> 116) nor an overshoot (116 -> 120) is waved through.
    for base_count, current_count in ((115, 116), (116, 120)):
        baseline = dict(mod.STRICT_EQUALITY_BASELINE)
        baseline["mutate_token_exempted"] = current_count
        monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", baseline)
        _bootstrapped, violations, _removed = mod._compute_ratchet_findings(
            {"mutate_token_exempted": base_count}
        )

        assert len(violations) == 1
        assert str(base_count) in violations[0]
        assert str(current_count) in violations[0]


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
