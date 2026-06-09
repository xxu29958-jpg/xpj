"""Known-debt gate for ``_audit_codebase.py`` + PR-Δ verification gate
for ``_audit_pr_delta_metrics.py``.

Two semantics, two baselines, two evaluators:

- :data:`CODEBASE_DEBT_LIMITS` + :func:`evaluate_debt` — debt counters
  (one-direction drift; improvement OK with INFO, regression FAIL).
- :data:`STRICT_EQUALITY_BASELINE` + :data:`BASELINE_RATCHET_UP` +
  :data:`BASELINE_RATCHET_DOWN` + :func:`evaluate_pr_delta_metrics` —
  ADR-0038 PR-Δ counters. Three layers stacked:

    1. **Strict equality** (all PR-Δ keys): current actual == current
       baseline. Both directions FAIL.

    2. **Baseline movement ratchet** (subset of keys): current baseline
       vs base baseline. UP-keys (tests, carriers) baseline can only
       grow; DOWN-keys (exempted) baseline can only shrink. Catches
       "baseline silently dropped to match silently-removed actual"
       collusion — strict equality alone doesn't.

    3. **Removed-key防绕** (all PR-Δ keys): keys present in base
       baseline must remain present in current baseline. Prevents
       "rename ``backend_pytest_count`` to ``backend_pytest_count_v2``
       and claim bootstrap" loophole. Key migration requires a
       dedicated migration PR, not a smuggle inside a cut-over PR.

  **Bootstrap exception** is the ONLY way a key skips ratchet: ``key
  not in base_baseline``. No flags, no env vars, no PR labels — purely
  data-shape-driven, self-extinguishing the moment the key lands in
  main's baseline.

  Base baseline source priority:
  - ``GITHUB_BASE_REF`` env var (set by GitHub Actions on PR events)
    via ``git show <base_ref>:<path>`` — the immutable PR base SHA,
    not a moving target.
  - ``origin/main`` fallback for local dev / non-PR runs.

  In PR CI (``GITHUB_BASE_REF`` set) failing to read base FAILs the
  audit. Local dev (no PR context) skips ratchet with INFO. This
  asymmetry is intentional: CI must never silently downgrade to
  "strict equality only".

Scope boundaries (don't let this mechanism bloat into a怪物)
-----------------------------------------------------------

This gate is targeted defense for high-risk surfaces. It is NOT a
universal quality gate. Three hard boundaries:

**1. Engagement is data-driven, not policy-imposed.**
   The gate only "engages" when the audit's counter actuals drift from
   baseline. README / UI text / color-only / non-routing bugfix PRs
   don't touch the receiving code → actuals don't move → no baseline
   bump required → audit passes silently. No path filter is configured
   in CI; the strict-equality semantics自然只在受管 surface 改动时才
   产生声明义务。

**2. Adding a new counter requires answering five questions in the PR
   that introduces it; failing any question = don't add the counter:**

   - Is it stable (won't drift with environment / time)?
   - Is it machine-verifiable (grep / collect-only / AST exact count)?
   - Does it defend against a real risk (not "seems useful")?
   - Can it be easily gamed (and if so, what守护 makes it un-gameable)?
   - Does it have a clear owner?

   Reviewer rejects a counter-addition PR if these aren't answered.
   This is the dam against "audit-creep" — every "let's also count X"
   gets the questions, most don't survive them.

**3. Numeric counters defend against silent regression, NOT prove
   quality.**

   ``backend_pytest_count`` / ``android_junit_test_method_count`` exist
   to catch "tests silently deleted in a refactor PR". They are NOT
   measures of test quality — count rising doesn't mean coverage rose.
   Quality measures are a different axis (critical-path tests, mutation
   tests, contract tests, route security matrix, tenant isolation
   cases, migration rollback, real E2E), and would be enforced by
   different mechanisms if/when added. Confusing the two leads to
   people writing trivial tests to make a number go up — defeats both
   purposes. The PR-Δ gate stays in its lane.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

DebtCounts = dict[str, int]

# Re-baselined for the v1.1 working tree (AI budget advisor + auth/migration
# hardening + this round's review fixes). ``files_over_500`` rose to 12 because
# the heavily-refactored ``background_task_service`` and the tenant-isolation
# tests in ``test_background_tasks`` legitimately grew past 500 — splitting
# cohesive files purely to stay under the line is the wrong trade. The lowered
# counters (nested_dict_args / service_public_no_private / unreferenced_modules)
# bank real reductions so they cannot silently regress later.
#
# ``route_layer_imports`` and ``mixed_return_functions`` are now 0: the audit
# was de-noised (route lane no longer counts the ``get_db`` DI import; the
# mixed-return lane skips declared Optionals and no longer attributes a nested
# closure's bare return to its parent), and the few genuine cases were moved
# into services (device_public_id / active_ledger_name) or behind TYPE_CHECKING.
# Both at 0 means any real route→model import or implicit-None return now fails.
CODEBASE_DEBT_LIMITS: DebtCounts = {
    # 12→13: ADR-0038 undo pushed routes/expenses.py past 500. 13→14: ADR-0041
    # self-describing items/splits tests grew test_expense_splits.py past 500.
    # Splitting cohesive files purely to stay under the line is the wrong trade.
    "files_over_500": 14,
    # PR-A expanded undo_reject_expense docstring (ABA + child resource
    # contract) tipped one function over the 80-line threshold; bank +1.
    "long_functions": 37,  # −4 PG-only slice 2 (retired SQLite migrator/validator); −1 slice 5 (retired cut-over machinery)
    "deep_nesting_functions": 6,
    "route_layer_imports": 0,
    "service_public_no_private": 4,
    "global_usage": 5,  # +1 ADR-0045 csrf startup-stash singleton; −2 PG-only slice 2 (retired _backup.py _sqlite_backup_done guard)
    "cached_singletons": 3,
    "nested_dict_args": 16,  # −1 PG-only slice 5 (retired cut-over machinery)
    "mixed_return_functions": 0,
    "broad_exception": 22,  # −1 PG-only slice 2 (retired SQLite migrator/validator)
    "generic_raises": 4,  # −3 PG-only slice 5 (retired v1_migration handler RuntimeError raises + mark_v1_cut_over)
    "todo_markers": 9,
    "hardcoded_urls": 12,  # +2 ADR-0027 Frankfurter default URL (config default, mirrors ECB inline pattern)
    "credentials_risk": 4,
    "n_plus_one": 2,
    # PR-A wires fetch_expense_updated_at_in_status (new in _query.py) into the
    # /web/pending route; bank the reduction so unreferenced_modules can't
    # silently re-creep.
    "unreferenced_modules": 206,  # +2 ADR-0043 tag_management_service + tag_undo_service (covered via /api/tags route tests, not direct import); +2 slice C web_tags + owner_console._tag_cleanup (HTTP-tested, not direct import); −15 PG-only slice 2 (retired _migrations/ + _validate/ submodules); −1 slice 5 (retired cut-over modules)
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
    regressions = [
        (key, counts[key], CODEBASE_DEBT_LIMITS[key])
        for key in sorted(CODEBASE_DEBT_LIMITS)
        if key in counts and counts[key] > CODEBASE_DEBT_LIMITS[key]
    ]
    improvements = [
        (key, counts[key], CODEBASE_DEBT_LIMITS[key])
        for key in sorted(CODEBASE_DEBT_LIMITS)
        if key in counts and counts[key] < CODEBASE_DEBT_LIMITS[key]
    ]

    print("== Gate. Known-debt baseline ==")
    if missing:
        print("FAIL: configured codebase debt counters were not reported:")
        for key in missing:
            print(f"  - {key}")
    if regressions:
        print("FAIL: codebase debt increased beyond the checked-in baseline:")
        for key, actual, limit in regressions:
            print(f"  - {key}: actual={actual}, allowed={limit}")
    if improvements:
        print("INFO: debt improved; lower CODEBASE_DEBT_LIMITS in this script:")
        for key, actual, limit in improvements:
            print(f"  - {key}: actual={actual}, old_limit={limit}")
    if not missing and not regressions:
        print(f"OK: {len(CODEBASE_DEBT_LIMITS)} counters at or below baseline.")
    print()
    return 1 if missing or regressions else 0


# ---------------------------------------------------------------------------
# ADR-0038 PR-Δ verification baseline (strict equality + ratchet)
# ---------------------------------------------------------------------------

# Baselines and policies all live in the gate file. The audit lane
# (``_audit_pr_delta_metrics.py``) only emits counter actuals and calls
# the public ``evaluate_pr_delta_metrics(counts)`` API; it doesn't
# import baseline internals or know which keys are ratcheted. This
# split is permanent — producers stay pure-data.
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
    # PR-A 6 routes (expense undo + recurring pause/resume); PR-B income_plan
    # archive/restore ×(api+web) = 4 more (atomic UPDATE WHERE + token); +4
    # ADR-0043 slice B /api/tags ×4; +5 slice C /web/tags ×4 + /owner tag-cleanup delete (OCC via Form).
    "mutate_token_carriers": 49,
    "mutate_token_exempted": 109,  # −2 PG-only slice 5 (retired /owner/migration-readiness cut-over + pre-v1-backup exemptions)
    "mutate_token_reason_admin_single_writer": 9,
    "mutate_token_reason_append_only_fact": 4,
    "mutate_token_reason_batch_db_write": 19,
    "mutate_token_reason_create_row": 26,
    "mutate_token_reason_enqueue_task": 0,  # −1 PG-only slice 5 (cut-over was the only enqueue_task route)
    "mutate_token_reason_external_side_effect": 4,  # −1 PG-only slice 5 (retired pre-v1-backup)
    "mutate_token_reason_governance_action": 8,
    "mutate_token_reason_read_only_compute": 3,
    "mutate_token_reason_session_rotation": 5,
    "mutate_token_reason_terminal_flag_flip": 23,
    "mutate_token_reason_upsert_bucket": 8,
    # +1 PR-A (/web recurring); +7 PR-B income_plan OCC; +4 PR-C bill_split
    # accept atomic-claim; +8 ADR-0041 Slice A row_version groundwork; +3
    # ADR-0041 self-describing items/splits responses (parent row_version in
    # items-replace, acknowledge-mismatch, splits-replace responses); +12 ADR-0042 Slice A idempotency helper tests; +5 Slice B PATCH idempotency tests; +12 Slice D-1 state-machine idempotency tests; +15 Slice D-2 rules/aliases/items idempotency tests (header-required×5, committed-but-unseen rule+items+alias, delete HIT rule+alias, in-progress×2, reuse×2); +5 Slice E-1 splits-replace idempotency tests (header-required, committed-but-unseen, stale-409, in-progress, reuse); +5 Slice E-2 recognize-text idempotency tests (same shape); +1 ADR-0042 tags-guard hardening (explicit {"tags":null} no longer clobbers); +10 Slice F goals/income-plan PATCH idempotency tests (header-required×2, committed-but-unseen goal+plan, stale-409×2, in-progress×2, reuse×2). +1 owner-console live DB dialect readiness test (ADR-0041 cut-over visibility). +11 ADR-0027 Frankfurter transport + weekend fallback + owner FX panel tests (parse×4, dispatcher, weekend-resolve, pre-history pending, run_once×2, owner 403 + manual refresh); +1 mutate exempt /owner/fx/refresh (upsert_bucket); +2 FX review follow-up (ecb dispatcher branch + run_fx_sync_once unexpected-error). +4 ADR-0043 slice A (legacy tags management-columns + snapshot-tables migration ×1; expense_tags mirror reconcile relink / orphan-removal / noop-idempotent ×3). +4 ADR-0043 slice A review follow-up (alembic ALTER-branch round-trip migration ×1; reconcile occ-effective-bump / unrelated-not-bumped / multi-batch ×3). +20 ADR-0043 slice B (tag management: 13 test_tag_management list/rename/delete/merge/viewer/isolation/auth/read-filter/self-merge/dedup + 7 test_tag_undo undo-restore/stale-409/partial-CAS/merge-undo/window-404/unknown-404/purge). +14 ADR-0043 slice C tag-mgmt UI (+7 test_web_app_tags, +3 test_owner_tag_cleanup, +4 route-inventory writer-only parametrize for the 4 /web/tags POST routes). +1 slice C follow-up (owner orphan-cleanup TOCTOU re-check skips a re-used tag). +3 ADR-0043 codex-review P1 (test_web_session_write_gate: web-session viewer write-gate × viewer-denied/member-allowed/not-listed-denied). +3 ADR-0043 review-2 (test_tag_management merge-id-order + orphan-guard service tests ×2; web_tasks cancel joins writer-only route-inventory parametrize ×1). +1 ADR-0043 review-3 (test_tag_management: _claim_merge_pair on a concurrently soft-deleted tag surfaces state_conflict 409, not tag_not_found 404). +1 ADR-0043 review follow-up (OpenAPI API/UploadLink error responses use project ErrorResponse, not HTTPValidationError). +4 ADR-0045 CSRF signing key (csrf_key_service get-or-create idempotent + non-placeholder; _csrf_secret prefers real env, rejects placeholder → per-install app_meta key; persisted key covers placeholder env on /web vs genuine-no-key fail-closed 500). +3 ADR-0045 follow-up (budget-advisor audit input-hash HMAC: per-install audit key rejects placeholder + is csrf-separated; compute_input_hash uses it; prefers a real env secret).
    "backend_pytest_count": 1602,  # −5 PG-only slice 4 (backup-validation reroute): dropped 2 backup-dialect-dispatch tests + 1 legacy restore_database delegation test + collapsed 3 SQLite-fixture owner-backup tests into 1 .dump test (slice 2 set 1626 from 1686); −19 slice 5 (retired test_owner_console_migration_readiness + test_v1_cutover cut-over tests + most of test_data_migration; rescued surviving coverage — 4 app_meta tests → test_app_meta_service, 1 timestamptz schema invariant → test_schema_invariants)
    # Android ``@Test`` count is enforced separately by the Android CI
    # lane (``:app:verifyTestCountBaseline`` gradle task against
    # ``android/audit/test_count_baseline.txt``). Cross-job coordination
    # is intentionally avoided — each side enforces its own contract,
    # at the cost of cut-over PRs that touch both sides needing to
    # update both baseline files. Android count is NOT listed here.
}


# Subset of STRICT_EQUALITY_BASELINE keys whose baseline value can ONLY grow
# vs base — decreasing = letting actual silently drop (lost token routes someone
# paid for). ``backend_pytest_count`` was REMOVED here for the PG-only slimming
# campaign (slices 2-5 delete already-PG-skipped SQLite tests); strict equality
# still forces its every change to be declared in this file's diff.
BASELINE_RATCHET_UP: frozenset[str] = frozenset({
    "mutate_token_carriers",
})

# Subset of STRICT_EQUALITY_BASELINE keys whose baseline value can ONLY
# shrink vs base. Exemptions in mutate-token ALLOWLIST should drain as
# routes graduate to carrying ``expected_row_version``, never grow back.
# Adding a route to ALLOWLIST requires an explicit ADR pointer per the
# v1.3 PR-2 ledger contract — this ratchet enforces that contract here.
BASELINE_RATCHET_DOWN: frozenset[str] = frozenset({
    "mutate_token_exempted",
})

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
      1. ``GITHUB_BASE_REF`` (GitHub Actions sets this on PR events to
         the target branch name; fetched as ``origin/<branch>``).
      2. ``XPJ_AUDIT_BASE_REF`` (manual override for ad-hoc CI).
      3. else: local ``refs/heads/main`` (``origin`` here is the dead GitHub mirror,
         so ``origin/main`` is stale) / CI push (``GITHUB_SHA`` set) → ``origin/main``.
    """
    explicit_ref = os.environ.get("GITHUB_BASE_REF") or os.environ.get("XPJ_AUDIT_BASE_REF")
    if explicit_ref:  # bare branch (e.g. ``main``) → fetched remote ``origin/main``
        git_ref = explicit_ref if "/" in explicit_ref else f"origin/{explicit_ref}"
    else:  # local: refs/heads/main (origin=dead GitHub); CI push (GITHUB_SHA): origin/main
        git_ref = "origin/main" if os.environ.get("GITHUB_SHA") else "refs/heads/main"
    backend_root = Path(__file__).resolve().parent.parent
    try:
        content = subprocess.check_output(
            ["git", "show", f"{git_ref}:backend/scripts/codebase_audit_gate.py"],
            cwd=backend_root,
            text=True,
            encoding="utf-8",  # Windows GBK default mangles Chinese in file content
            errors="replace",
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return (False, {})
    namespace: dict = {}
    try:
        # Trusted source (our own gate file at base). exec is safer than
        # AST extraction here because the dict literal could change form
        # across PRs and AST patterns would couple to syntax shape.
        exec(content, namespace)  # noqa: S102 — trusted source
    except Exception:  # noqa: BLE001 — base may have an import error; treat as unreadable
        return (False, {})
    baseline = namespace.get("STRICT_EQUALITY_BASELINE")
    if not isinstance(baseline, dict):
        # File readable but variable missing → integral-bootstrap state
        # (this is exactly the prep PR's situation against main).
        return (True, {})
    return (True, baseline)


def _is_pr_ci_context() -> bool:
    """True when running in PR CI (GitHub Actions PR event). Distinguishes
    "base required, must FAIL if unreadable" from "local dev, skip OK"."""
    return bool(os.environ.get("GITHUB_BASE_REF"))


def _compute_strict_equality_findings(
    counts: DebtCounts,
) -> tuple[list[str], list[tuple[str, int, int]], list[str]]:
    """Layer 1: returns (missing, mismatches, extras) against STRICT_EQUALITY_BASELINE."""
    missing = sorted(set(STRICT_EQUALITY_BASELINE) - set(counts))
    mismatches = [
        (key, counts[key], STRICT_EQUALITY_BASELINE[key])
        for key in sorted(STRICT_EQUALITY_BASELINE)
        if key in counts and counts[key] != STRICT_EQUALITY_BASELINE[key]
    ]
    extras = sorted(set(counts) - set(STRICT_EQUALITY_BASELINE))
    return missing, mismatches, extras


def _compute_ratchet_findings(
    base_baseline: dict[str, int],
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
        if key in BASELINE_RATCHET_UP and current_val < base_val:
            movement_violations.append(
                f"  - {key} (UP-only): base={base_val}, current={current_val} "
                f"(dropped by {base_val - current_val}). Tests/coverage should "
                f"accumulate, not vanish. Strict equality alone misses this when "
                f"actuals dropped in lockstep — this layer catches it."
            )
        elif key in BASELINE_RATCHET_DOWN and current_val > base_val:
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
            "FAIL: actual != current baseline. Update STRICT_EQUALITY_BASELINE "
            "in the SAME PR if change is intentional; otherwise the PR has an "
            "undeclared regression. Both directions fail:"
        )
        for key, actual, baseline in mismatches:
            diff = actual - baseline
            sign = "+" if diff > 0 else ""
            print(f"  - {key}: actual={actual}, current_baseline={baseline} ({sign}{diff})")
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
            "FAIL: in PR CI but couldn't read base baseline. Possible causes: "
            "(a) checkout was shallow (fetch-depth=1, can't reach base SHA); "
            "(b) base ref not fetched. Fix CI config — do NOT downgrade to "
            "strict-equality-only as a workaround:"
        )
        print(f"  - GITHUB_BASE_REF={os.environ.get('GITHUB_BASE_REF')}")


def _print_info_lines(base_readable: bool, bootstrapped: list[str]) -> None:
    if bootstrapped:
        # INFO, not FAIL. Bootstrap is the legitimate first-encounter state.
        print(
            "INFO: keys not in base baseline (bootstrap — strict equality applies, "
            "ratchet skipped this PR; auto-extinguishes next PR after merge):"
        )
        for key in bootstrapped:
            print(f"  - {key}")
    if not base_readable and not _is_pr_ci_context():
        print(
            "INFO: base baseline unreadable (local dev — no PR context). "
            "Ratchet + removed-key checks skipped. In PR CI these would FAIL "
            "rather than skip, so this is not a CI bypass."
        )


def _print_ok_line(base_readable: bool, bootstrapped: list[str]) -> None:
    passed = len(STRICT_EQUALITY_BASELINE)
    if base_readable:
        msg = f"OK: {passed} PR-Δ counters pass strict + ratchet + removed-key checks"
        if bootstrapped:
            msg += f" ({len(bootstrapped)} bootstrapped this PR)"
    else:
        msg = f"OK: {passed} PR-Δ counters match baseline exactly (ratchet skipped — local)"
    print(msg + ".")


def evaluate_pr_delta_metrics(counts: DebtCounts) -> int:
    """ADR-0038 PR-Δ gate. Three-layer policy + 5-class output.

    Layers (all stacked, each can FAIL independently):

    1. **Strict equality** — every key in STRICT_EQUALITY_BASELINE
       must appear in ``counts`` and equal its baseline value. Drift
       in EITHER direction FAILs. Counters in ``counts`` without a
       baseline entry FAIL ("unprotected new counter").

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
    base_unreadable_but_required = not base_readable and _is_pr_ci_context()
    bootstrapped: list[str] = []
    movement_violations: list[str] = []
    removed_keys: list[str] = []
    if base_readable:
        bootstrapped, movement_violations, removed_keys = _compute_ratchet_findings(base_baseline)

    print("== Gate. ADR-0038 PR-Δ verification (strict-equality + ratchet) ==")
    _print_strict_equality_failures(counts, missing, mismatches, extras)
    _print_ratchet_failures(movement_violations, removed_keys, base_unreadable_but_required)
    _print_info_lines(base_readable, bootstrapped)

    fail = bool(
        missing or mismatches or extras
        or movement_violations or removed_keys or base_unreadable_but_required
    )
    if not fail:
        _print_ok_line(base_readable, bootstrapped)
    print()
    return 1 if fail else 0
