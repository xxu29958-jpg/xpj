"""Known-debt and PR-Δ gates for backend audit lanes.

``CODEBASE_DEBT_LIMITS`` is a one-way debt ceiling for
``_audit_codebase.py``: regressions fail, improvements print INFO so the
baseline can be lowered in the same cleanup slice. Physical size entries are
review references only; their counts and completeness remain visible.

``STRICT_EQUALITY_BASELINE`` protects PR-Δ counters from
``_audit_pr_delta_metrics.py``. Structural counters use exact current
actuals, while responsibility-owned test counts are minimum floors. The gate
also checks directional movement vs the base branch for ratcheted keys and
removed-key detection so managed counters cannot be renamed away.

Bootstrap is purely data-shaped: a new key absent from the base baseline
skips only the directional ratchet for that PR, while strict equality
still applies. PR CI must be able to read the base file via git; local
dev without PR context may skip that comparison with an INFO line.

Scope: these numeric gates defend high-risk surfaces against silent drift.
They are not universal quality scores; adding a counter still requires a
stable, machine-verifiable risk and a clear owner. See ADR-0038 for the
full policy history and CODE-2026-07-01 for provenance-comment cleanup.
"""

from __future__ import annotations

import os
from pathlib import Path

from adr_contract_git import has_auditable_ci_context, select_ratchet_base
from pr_delta_baselines import (
    TEST_COUNT_BASELINES,
    baseline_policy_mismatches,
    baseline_retirement_allowed,
    git_show_text,
    load_current_test_count_baselines,
    parse_count_baseline,
    strict_baseline_literal,
)

DebtCounts = dict[str, int]

_strict_baseline_selection_error: str | None = None
_strict_baseline_selected_ref: str | None = None
_strict_baseline_selected_commit: str | None = None

# ``CODEBASE_DEBT_LIMITS`` is active configuration, not an audit log. Keep the
# current ceilings here and put detailed ratchet provenance in commits/PR notes.
# Zero ceilings mean the scanner lane is now strict and any reintroduction fails.
CODEBASE_SIZE_SIGNALS = frozenset({"files_over_500", "long_functions"})

CODEBASE_DEBT_LIMITS: DebtCounts = {
    # Keep active ceilings here. Older ratchet provenance belongs in git history,
    # not in executable override chains.
    "files_over_500": 11,  # Historical reference for review, not a debt ceiling.
    "long_functions": 3,  # Physical spans include fixtures, declarations and comments.
    "deep_nesting_functions": 0,
    "route_layer_imports": 0,
    "service_public_no_private": 1,
    "global_usage": 0,  # 2026-07-08: process-local CSRF/executor/Windows-task state moved behind lifecycle stores.
    "cached_singletons": 3,
    "nested_dict_args": 0,  # 2026-07-08: JSON/DTO boundary signatures use named contracts.
    "mixed_return_functions": 0,
    "broad_exception": 0,  # 2026-07-08: remaining broad catches narrowed to cleanup/fail-soft exception families.
    "generic_raises": 0,  # 2026-07-08: remaining direct RuntimeError raises now use narrow startup/service contract exceptions.
    "todo_markers": 0,
    "hardcoded_urls": 5,  # 2026-07-08: removed prose/comment URL examples; production endpoint defaults remain explicit debt.
    "credentials_risk": 0,
    "n_plus_one": 0,
    "unreferenced_modules": 2,
    "import_cycles": 0,
    "sql_outside_database": 0,
    "import_star": 0,
    "smelly_names": 0,
    "unannotated_long_functions": 0,
    "bare_except": 0,
    "swallowed_exceptions": 0,
    "hardcoded_paths": 0,
    "magic_numbers": 0,
}


def evaluate_debt(counts: DebtCounts) -> int:
    missing = sorted(set(CODEBASE_DEBT_LIMITS) - set(counts))
    extras = sorted(set(counts) - set(CODEBASE_DEBT_LIMITS))
    measured_keys = sorted((counts.keys() & CODEBASE_DEBT_LIMITS.keys()) - CODEBASE_SIZE_SIGNALS)
    regressions = [
        (key, counts[key], CODEBASE_DEBT_LIMITS[key])
        for key in measured_keys
        if counts[key] > CODEBASE_DEBT_LIMITS[key]
    ]
    improvements = [
        (key, counts[key], CODEBASE_DEBT_LIMITS[key])
        for key in measured_keys
        if counts[key] < CODEBASE_DEBT_LIMITS[key]
    ]

    print("== Gate. Known-debt baseline ==")
    print("REVIEW: physical size signals require responsibility review, not mechanical splitting:")
    for key in sorted(CODEBASE_SIZE_SIGNALS & counts.keys()):
        print(f"  - {key}={counts[key]} (reference={CODEBASE_DEBT_LIMITS[key]})")
    if missing:
        print("FAIL: configured codebase debt counters were not reported:")
        for key in missing:
            print(f"  - {key}")
    if extras:
        print("FAIL: audit reported codebase debt counters with no baseline entry:")
        for key in extras:
            print(f"  - {key}={counts[key]}")
    if regressions:
        print("FAIL: codebase debt increased beyond the checked-in baseline:")
        for key, actual, limit in regressions:
            print(f"  - {key}: actual={actual}, allowed={limit}")
    if improvements:
        print("INFO: debt improved; lower CODEBASE_DEBT_LIMITS in this script:")
        for key, actual, limit in improvements:
            print(f"  - {key}: actual={actual}, old_limit={limit}")
    if not missing and not extras and not regressions:
        print(f"OK: all {len(CODEBASE_DEBT_LIMITS)} counters reported; hard debt counters at or below baseline.")
    print()
    return 1 if missing or extras or regressions else 0


# ---------------------------------------------------------------------------
# ADR-0038 PR-Δ verification baseline (strict equality + ratchet)
# ---------------------------------------------------------------------------

# Policies and structural baselines live in this gate. Test counts live beside
# the responsibility that owns them, so a backend test bump cannot accidentally
# trigger Android/Desktop/Windows qualification. The audit lane
# (``_audit_pr_delta_metrics.py``) remains a pure-data producer.
#
# Cut-over PRs (PR-A/B/C/D etc) declare expected Δ by bumping these
# entries in the SAME diff that changes the actual counters. Both
# directions of strict equality fail; ratchet violations also fail
# regardless of strict-equality outcome (the two checks compose).
#
# Snapshot captured on chore/audit-delta-baseline-prep against current
# main. See ``_audit_pr_delta_metrics.py`` docstring for what each
# counter is and how it's computed.
STRICT_EQUALITY_BASELINE: DebtCounts = {
    "mutate_token_carriers": 141,  # Uncategorized bulk-set now carries the original selection's OCC versions.
    "mutate_token_exempted": 148,  # Adds duplicate-decision read-only review; bulk-set retains OCC.
    "mutate_token_reason_admin_single_writer": 16,
    "mutate_token_reason_append_only_fact": 3,
    "mutate_token_reason_batch_db_write": 16,
    "mutate_token_reason_create_row": 42,  # New rows with original-key receipts; existing OCC routes unchanged.
    "mutate_token_reason_enqueue_task": 2,
    "mutate_token_reason_external_side_effect": 8,
    "mutate_token_reason_governance_action": 8,
    "mutate_token_reason_read_only_compute": 6,
    "mutate_token_reason_session_rotation": 8,
    "mutate_token_reason_terminal_flag_flip": 35,
    "mutate_token_reason_upsert_bucket": 4,
}
STRICT_EQUALITY_BASELINE.update(load_current_test_count_baselines())

# Android executed JVM/connected totals are enforced separately by the Android
# CI lane (``:app:assertAndroidTestCountEqualsBaseline`` and the connected task
# against Gradle/AGP JUnit XML plus ``android/audit/test_count_baseline.txt``).
# Cross-job coordination is intentionally avoided: each side enforces its own
# contract, at the cost of cut-over PRs that touch both sides needing to update
# both baseline files. Android counts are NOT listed here.
# Total test counts are reconciliation signals, not coverage proofs. Their
# checked-in values are minimum floors: additions do not require baseline churn,
# while a drop still requires an explicit reviewed floor movement. The installer
# suite remains a release-critical monotonic floor except for exact one-time
# removals of physically retired lifecycle harnesses.
BASELINE_RATCHET_UP: frozenset[str] = frozenset(
    {
        "installer_pytest_count",
        "mutate_token_carriers",
    }
)

# DOWN-only keys may shrink as routes graduate; they must not grow back.
# New ALLOWLIST routes need explicit ADR pointers per v1.3 PR-2.
BASELINE_RATCHET_DOWN: frozenset[str] = frozenset(
    {
        "mutate_token_exempted",
    }
)
_MUTATE_TOKEN_EXEMPTION_ADMISSIONS = (
    # ADR-0038 create_row / Rev3.2 section 6.6 Reference Library: category API,
    # tag API, shared Web create adapter and native saved-query create have no predecessor row. Their
    # common command keeps original actor/key receipts and unique ledger names;
    # duplicates never restore old objects. All 138 original OCC carriers stay protected,
    # with two new saved-query API carriers. Uncategorized bulk-set graduates from
    # its old batch exemption to original-selection OCC. The duplicate decision
    # review adds ADR-0038 read_only_compute: it reads the pair without changing
    # a fact or writing a receipt, as the existing refusal/recovery browser gate
    # verifies. Its later keep/reject commands retain OCC; the net admission is four.
    # Admit only this exact base/count transition, not general exemption growth.
    ("92983e731072c2daa538bb61a3e782a5c4e60d5e", 144, 148),
    # One existing Ledger.name fact; three adapters share the Owner/credential
    # lock and field CAS. No financial OCC carrier or persistence owner changes.
    ("30beaeca2db6e76e72d7bd5acc5cd54a37212883", 141, 144),
    # Account identity owns its display label. Both adapters use expected_name
    # CAS and the existing credential lock, without a financial OCC carrier.
    ("afa32490213c9752c5ceedec07ad5425ae8f42e0", 139, 141),
    # Four Web adapters reuse existing Account device commands and the API's
    # classifications; no financial writer, OCC carrier or identity owner moves.
    ("3eca4d4f0e525cda0e6abc7d4734b5a36c4ddb7d", 135, 139),
    # ADR-0036/0038 external_side_effect: four settings groups publish through the
    # existing protected settings file lock, not a financial row. Connection
    # changes revoke consent; confirmation checks its exact saved revision.
    # The fifth route only sends a fixed example to the saved model provider.
    # Maintenance changes acknowledge deletion scope before enabling cleanup;
    # upload defaults never rewrite already issued link expiry timestamps.
    # No OCC-bearing financial route changes classification.
    ("f971f28a0fb53031626209f1a4432414b42ee1fa", 130, 135),
    # ADR-0030/0038 enqueue_task; TICKETBOX_ORIGINAL_INTEGRITY_CONTRACT continuation.
    # Two new Local Owner task admissions have no predecessor financial row:
    # original UUID receipts + conditional task claims + exact file/ref checks
    # own their concurrency. All 138 existing OCC carriers remain protected.
    ("0e4932d933bec3d2d5618d736d61359360cd7884", 128, 130),
    # ADR-0038 create_row: one new ledger-shared saved-query creation. The
    # service enforces unique names + actor/key receipts; edit/delete keep OCC.
    ("8e5529e49434c7d0650172cf7fc40668446627e2", 128, 129),
    # A3: API/Web manual fixed-expense creates have no predecessor row version.
    ("0a0d2be96e5786ffcaa65588f960dea291098abd", 128, 130),
    # PR #427 follows ADR-0038's guarded terminal/read-only classification:
    # API/Web reject + withdraw latch proposal state and keep a durable receipt;
    # native preview reads only. Create/accept carry both real debt OCC tokens.
    # Only this exact base/count hop is admitted; future growth still fails.
    ("2d9ffd655ad9a6612049c0324ea7af6a4b0008a3", 124, 129),
)

# ``mutate_token_reason_<code>`` counters are NOT in either ratchet set:
# they're distribution-shift indicators (PR-D's ``terminal_flag_flip``
# split moves routes between codes; individual code counts can rise or
# fall legitimately). They still get strict-equality enforcement —
# moving them without bumping baseline still FAILs.


def _read_base_strict_baseline() -> tuple[bool, dict[str, int]]:
    """Return ``(base_readable, baseline_dict)``. Tuple distinguishes
    three states that have different gate consequences:

      - ``(True, {key: value, ...})``: base readable AND
        ``STRICT_EQUALITY_BASELINE`` was defined at base — apply ratchet
        + removed-key checks normally.
      - ``(True, {})``: base readable but the variable was NOT defined
        at base (e.g. this prep PR — the dict is being introduced for
        the first time). Every current key is integral-bootstrap; skip
        ratchet (no base value to compare against) but still enforce
        strict equality on each.
      - ``(False, {})``: base truly unreadable (git show failed —
        shallow checkout in PR CI is the common cause). In PR CI this
        is a FAIL; locally it's INFO-skip.

    Base ref priority:
      1. ``XPJ_AUDIT_BASE_REF`` (the workflow scope supplies the exact PR
         target, pre-push, or default-branch qualification base SHA).
      2. ``GITHUB_BASE_REF`` fallback (the CI runner sets the target branch
         name on PR events; fetched as ``origin/<branch>``).
      3. else: local ``refs/heads/main`` / CI push (``GITHUB_SHA`` set) →
         ``origin/main`` (GitHub main on cloud CI).
    """
    git_ref = _strict_baseline_git_ref()
    if git_ref is None:
        return (False, {})
    backend_root = Path(__file__).resolve().parent.parent
    content = git_show_text(
        git_ref,
        "backend/scripts/codebase_audit_gate.py",
        cwd=backend_root,
    )
    if content is None:
        return (False, {})
    try:
        baseline = strict_baseline_literal(content)
    except (SyntaxError, ValueError):
        return (False, {})
    if baseline is None:
        # File readable but variable missing → integral-bootstrap state
        # (this is exactly the prep PR's situation against main).
        return (True, {})
    for key, path in TEST_COUNT_BASELINES.items():
        count_text = git_show_text(git_ref, path.as_posix(), cwd=backend_root)
        if count_text is not None:
            try:
                baseline[key] = parse_count_baseline(
                    count_text,
                    source=f"{git_ref}:{path.as_posix()}",
                )
            except RuntimeError:
                return (False, {})
        # Before the baseline files existed, both counters lived in the gate
        # literal. Keeping that value makes this data migration auditable.
    return (True, baseline)


def _strict_baseline_git_ref() -> str | None:
    global _strict_baseline_selected_commit, _strict_baseline_selected_ref, _strict_baseline_selection_error

    backend_root = Path(__file__).resolve().parent.parent
    selected, error = select_ratchet_base(backend_root.parent, dict(os.environ))
    _strict_baseline_selection_error = error
    _strict_baseline_selected_ref = None if selected is None else selected.ref
    _strict_baseline_selected_commit = None if selected is None else selected.commit
    return None if selected is None else selected.commit


def _strict_baseline_base_is_required() -> bool:
    """Whether this invocation supplied or implied an auditable CI base.

    Base selection and fail-closed policy are one contract: an exact ref used by
    push/manual lanes is just as mandatory as ``GITHUB_BASE_REF`` in PR CI.
    """
    if os.environ.get("XPJ_AUDIT_BASE_REF", "").strip():
        return True
    return has_auditable_ci_context(dict(os.environ))


def _compute_strict_equality_findings(
    counts: DebtCounts,
) -> tuple[list[str], list[tuple[str, int, int]], list[str]]:
    """Layer 1: return missing, policy mismatches, and unowned extras."""
    missing = sorted(set(STRICT_EQUALITY_BASELINE) - set(counts))
    mismatches = baseline_policy_mismatches(counts, STRICT_EQUALITY_BASELINE)
    extras = sorted(set(counts) - set(STRICT_EQUALITY_BASELINE))
    return missing, mismatches, extras


def _compute_ratchet_findings(
    base_baseline: dict[str, int],
    *,
    base_commit: str | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Layer 2/3: returns (bootstrapped, movement_violations, removed_keys) by
    walking STRICT_EQUALITY_BASELINE keys against the base baseline dict."""
    bootstrapped: list[str] = []
    movement_violations: list[str] = []
    for key in sorted(STRICT_EQUALITY_BASELINE):
        current_val = STRICT_EQUALITY_BASELINE[key]
        if key not in base_baseline:
            bootstrapped.append(key)
            continue  # bootstrap: skip ratchet, strict equality already covered
        base_val = base_baseline[key]
        admitted = (
            key == "mutate_token_exempted"
            and (base_commit, base_val, current_val) in _MUTATE_TOKEN_EXEMPTION_ADMISSIONS
        )
        retirement = baseline_retirement_allowed(key, base_commit, base_val, current_val)
        if key in BASELINE_RATCHET_UP and current_val < base_val and not retirement:
            movement_violations.append(
                f"  - {key} (UP-only): base={base_val}, current={current_val} "
                f"(dropped by {base_val - current_val}). Tests/coverage should "
                f"accumulate, not vanish. Strict equality alone misses this when "
                f"actuals dropped in lockstep — this layer catches it."
            )
        elif key in BASELINE_RATCHET_DOWN and current_val > base_val and not admitted:
            movement_violations.append(
                f"  - {key} (DOWN-only): base={base_val}, current={current_val} "
                f"(rose by {current_val - base_val}). Exemptions should drain as "
                f"routes graduate; adding to ALLOWLIST needs an explicit ADR pointer."
            )
    removed_keys = sorted(set(base_baseline) - set(STRICT_EQUALITY_BASELINE))
    return bootstrapped, movement_violations, removed_keys


def _print_strict_equality_failures(
    counts: DebtCounts,
    missing: list[str],
    mismatches: list[tuple[str, int, int]],
    extras: list[str],
) -> None:
    if missing:
        print("FAIL: baseline entries that the audit lane didn't report:")
        for key in missing:
            print(f"  - {key}")
    if mismatches:
        print(
            "FAIL: actual violates its current baseline policy. Update the "
            "owning baseline in the SAME PR only when the policy movement is "
            "intentional and reviewed:"
        )
        for key, actual, baseline in mismatches:
            diff = actual - baseline
            sign = "+" if diff > 0 else ""
            policy = "minimum" if key in TEST_COUNT_BASELINES else "exact"
            print(f"  - {key}: actual={actual}, current_baseline={baseline} policy={policy} ({sign}{diff})")
    if extras:
        print(
            "FAIL: audit reported counters with no baseline entry. Add to "
            "STRICT_EQUALITY_BASELINE in the SAME PR (otherwise unprotected):"
        )
        for key in extras:
            print(f"  - {key}={counts[key]}")


def _print_ratchet_failures(
    movement_violations: list[str],
    removed_keys: list[str],
    base_unreadable_but_required: bool,
) -> None:
    if movement_violations:
        print(
            "FAIL: current baseline moved the WRONG direction vs base baseline. "
            "Strict equality passes when baseline and actual drop together — "
            "ratchet exists to catch that collusion:"
        )
        for line in movement_violations:
            print(line)
    if removed_keys:
        print(
            "FAIL: keys present in base baseline are missing from current baseline. "
            "Key removal / rename /摘出 STRICT_EQUALITY_BASELINE is a defrocking "
            "of a managed counter — must be a dedicated migration PR with explicit "
            "rationale, never smuggled inside a cut-over PR:"
        )
        for key in removed_keys:
            print(f"  - {key} (was in base, gone in current)")
    if base_unreadable_but_required:
        print(
            "FAIL: CI/exact-base audit couldn't read the required base baseline. Possible causes: "
            "(a) checkout was shallow (fetch-depth=1, can't reach base SHA); "
            "(b) base ref not fetched. Fix CI config — do NOT downgrade to "
            "strict-equality-only as a workaround:"
        )
        print(f"  - XPJ_AUDIT_BASE_REF={os.environ.get('XPJ_AUDIT_BASE_REF')}")
        print(f"  - GITHUB_BASE_REF={os.environ.get('GITHUB_BASE_REF')}")
        print(f"  - GITHUB_SHA={os.environ.get('GITHUB_SHA')}")
        print(f"  - selected_ref={_strict_baseline_selected_ref}")
        print(f"  - selection_error={_strict_baseline_selection_error}")


def _print_info_lines(base_readable: bool, bootstrapped: list[str]) -> None:
    if bootstrapped:
        # INFO, not FAIL. Bootstrap is the legitimate first-encounter state.
        print(
            "INFO: keys not in base baseline (bootstrap — strict equality applies, "
            "ratchet skipped this PR; auto-extinguishes next PR after merge):"
        )
        for key in bootstrapped:
            print(f"  - {key}")
    if not base_readable and not _strict_baseline_base_is_required():
        print(
            "INFO: base baseline unreadable (local dev — no CI/exact-base context). "
            "Ratchet + removed-key checks skipped. In PR CI these would FAIL "
            "rather than skip, so this is not a CI bypass."
        )


def _print_ok_line(base_readable: bool, bootstrapped: list[str]) -> None:
    passed = len(STRICT_EQUALITY_BASELINE)
    if base_readable:
        msg = f"OK: {passed} PR-Δ counters pass baseline policies + ratchet + removed-key checks"
        if bootstrapped:
            msg += f" ({len(bootstrapped)} bootstrapped this PR)"
    else:
        msg = f"OK: {passed} PR-Δ counters pass current baseline policies (ratchet skipped — local)"
    print(msg + ".")


def evaluate_pr_delta_metrics(counts: DebtCounts) -> int:
    """ADR-0038 PR-Δ gate. Three-layer policy + 5-class output.

    Layers (all stacked, each can FAIL independently):

    1. **Current baseline policy** — every key in
       STRICT_EQUALITY_BASELINE must appear in ``counts``. Structural
       counters equal their baseline exactly; test-count keys stay at or
       above their minimum floor. Counters without an entry FAIL
       ("unprotected new counter").

    2. **Baseline movement ratchet** — for ``BASELINE_RATCHET_UP`` keys,
       current baseline must be ``>=`` base baseline; for
       ``BASELINE_RATCHET_DOWN`` keys, ``<=``. Catches the
       "baseline silently dropped to match silently-removed actual"
       collusion that strict equality alone misses.

    3. **Removed-key防绕** — keys present in base baseline must remain
       in current baseline. Prevents renaming a key
       (``backend_pytest_count`` → ``backend_pytest_count_v2``) to
       claim bootstrap exemption.

    Bootstrap exception: a key not present in base baseline skips ONLY
    the ratchet check (layer 2). Strict equality (layer 1) still
    applies. This is purely data-driven — the moment a key lands in
    main's baseline, bootstrap自动失效 for that key. No flags, no
    overrides.

    Composed of helper functions to stay under the C901 complexity gate;
    each helper owns one concern (compute strict layer / compute ratchet
    layer / print strict failures / print ratchet failures / print info /
    print final OK line).
    """
    missing, mismatches, extras = _compute_strict_equality_findings(counts)

    base_readable, base_baseline = _read_base_strict_baseline()
    base_unreadable_but_required = not base_readable and _strict_baseline_base_is_required()
    bootstrapped: list[str] = []
    movement_violations: list[str] = []
    removed_keys: list[str] = []
    if base_readable:
        bootstrapped, movement_violations, removed_keys = _compute_ratchet_findings(
            base_baseline,
            base_commit=_strict_baseline_selected_commit,
        )

    print("== Gate. ADR-0038 PR-Δ verification (exact/floor policies + ratchet) ==")
    _print_strict_equality_failures(counts, missing, mismatches, extras)
    _print_ratchet_failures(movement_violations, removed_keys, base_unreadable_but_required)
    _print_info_lines(base_readable, bootstrapped)

    fail = bool(missing or mismatches or extras or movement_violations or removed_keys or base_unreadable_but_required)
    if not fail:
        _print_ok_line(base_readable, bootstrapped)
    print()
    return 1 if fail else 0
