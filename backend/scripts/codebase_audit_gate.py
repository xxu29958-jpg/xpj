"""Known-debt and PR-Δ gates for backend audit lanes.

``CODEBASE_DEBT_LIMITS`` is a one-way debt ceiling for
``_audit_codebase.py``: regressions fail, improvements print INFO so the
baseline can be lowered in the same cleanup slice.

``STRICT_EQUALITY_BASELINE`` protects PR-Δ counters from
``_audit_pr_delta_metrics.py``. It composes three checks: exact current
actuals, directional movement vs the base branch for ratcheted keys, and
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
import subprocess
from pathlib import Path

from adr_contract_git import has_auditable_ci_context, select_ratchet_base

DebtCounts = dict[str, int]

_strict_baseline_selection_error: str | None = None
_strict_baseline_selected_ref: str | None = None

# ``CODEBASE_DEBT_LIMITS`` is active configuration, not an audit log. Keep the
# current ceilings here and put detailed ratchet provenance in commits/PR notes.
# Zero ceilings mean the scanner lane is now strict and any reintroduction fails.
CODEBASE_DEBT_LIMITS: DebtCounts = {
    # Keep active ceilings here. Older ratchet provenance belongs in git history,
    # not in executable override chains.
    "files_over_500": 14,
    "long_functions": 5,  # 2026-07-09: bill-split invitation accept flow split.
    "deep_nesting_functions": 0,
    "route_layer_imports": 0,
    "service_public_no_private": 3,
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
    "unreferenced_modules": 215,  # Noisy lane; ratcheted to the current measured floor.
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
        print(f"OK: {len(CODEBASE_DEBT_LIMITS)} counters at or below baseline.")
    print()
    return 1 if missing or extras or regressions else 0


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
    "mutate_token_carriers": 77,
    "mutate_token_exempted": 123,
    "mutate_token_reason_admin_single_writer": 10,
    "mutate_token_reason_append_only_fact": 4,
    "mutate_token_reason_batch_db_write": 19,
    "mutate_token_reason_create_row": 32,
    "mutate_token_reason_enqueue_task": 0,
    "mutate_token_reason_external_side_effect": 4,
    "mutate_token_reason_governance_action": 8,
    "mutate_token_reason_read_only_compute": 4,
    "mutate_token_reason_session_rotation": 6,
    "mutate_token_reason_terminal_flag_flip": 28,
    "mutate_token_reason_upsert_bucket": 8,
    "backend_pytest_count": 2674,
    "installer_pytest_count": 105,  # Includes Manager packaging and maintenance-gate contracts.
}

# Android ``@Test`` count is enforced separately by the Android CI lane
# (``:app:assertAndroidTestCountEqualsBaseline`` gradle task against
# ``android/audit/test_count_baseline.txt``). Cross-job coordination is
# intentionally avoided: each side enforces its own contract, at the cost of
# cut-over PRs that touch both sides needing to update both baseline files.
# Android count is NOT listed here.
# UP-only keys cannot drop vs base; strict equality alone could miss lockstep
# baseline/actual reductions. ``backend_pytest_count`` is strict-only, while
# the release-critical installer behavior suite is also a monotonic floor.
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
_ADR_0049_EXEMPTED_GRANDFATHER = (
    122,
    123,
)  # Desktop two-phase credential (PR #219): POST /api/auth/desktop/activate adds one session_rotation exemption — it carries attempt-proof replay instead of OCC (ledger row in _mutate_token_ledger.py). The name is historical (first used for ADR-0049); it is the generic single in-flight exemption-add hop, previously (121, 122) for the ADR-0053 web merchant catalog create.

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
      1. ``XPJ_AUDIT_BASE_REF`` (the workflow supplies the exact PR target
         SHA / pre-push SHA; manual runs supply their exact pre-change SHA).
      2. ``GITHUB_BASE_REF`` fallback (the CI runner sets the target branch
         name on PR events; fetched as ``origin/<branch>``).
      3. else: local ``refs/heads/main`` / CI push (``GITHUB_SHA`` set) →
         ``origin/main`` (GitHub main on cloud CI).
    """
    git_ref = _strict_baseline_git_ref()
    if git_ref is None:
        return (False, {})
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


def _strict_baseline_git_ref() -> str | None:
    global _strict_baseline_selected_ref, _strict_baseline_selection_error

    backend_root = Path(__file__).resolve().parent.parent
    selected, error = select_ratchet_base(backend_root.parent, dict(os.environ))
    _strict_baseline_selection_error = error
    _strict_baseline_selected_ref = None if selected is None else selected.ref
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
        adr_0049_exempt = key == "mutate_token_exempted" and (base_val, current_val) == _ADR_0049_EXEMPTED_GRANDFATHER
        if key in BASELINE_RATCHET_UP and current_val < base_val:
            movement_violations.append(
                f"  - {key} (UP-only): base={base_val}, current={current_val} "
                f"(dropped by {base_val - current_val}). Tests/coverage should "
                f"accumulate, not vanish. Strict equality alone misses this when "
                f"actuals dropped in lockstep — this layer catches it."
            )
        elif key in BASELINE_RATCHET_DOWN and current_val > base_val and not adr_0049_exempt:
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
    base_unreadable_but_required = not base_readable and _strict_baseline_base_is_required()
    bootstrapped: list[str] = []
    movement_violations: list[str] = []
    removed_keys: list[str] = []
    if base_readable:
        bootstrapped, movement_violations, removed_keys = _compute_ratchet_findings(base_baseline)

    print("== Gate. ADR-0038 PR-Δ verification (strict-equality + ratchet) ==")
    _print_strict_equality_failures(counts, missing, mismatches, extras)
    _print_ratchet_failures(movement_violations, removed_keys, base_unreadable_but_required)
    _print_info_lines(base_readable, bootstrapped)

    fail = bool(missing or mismatches or extras or movement_violations or removed_keys or base_unreadable_but_required)
    if not fail:
        _print_ok_line(base_readable, bootstrapped)
    print()
    return 1 if fail else 0
