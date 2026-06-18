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
  - ``GITHUB_BASE_REF`` env var (set by the CI runner on PR events)
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
    "files_over_500": 17,  # +1 ADR-0049 #4: models/debt.py crossed 500 (498→534) adding member-repayment + RepaymentDraft FK/CHECK backstops with the load-bearing circular-FK/use_alter note. +1 slice 3: routes/debts.py (member-repayment-proposal routes; proposal tests split by concern stay under the gate).
    # PR-A expanded undo_reject_expense docstring (ABA + child resource
    # contract) tipped one function over the 80-line threshold; bank +1.
    "long_functions": 37,  # −4 PG-only slice 2 (retired SQLite migrator/validator); −1 slice 5 (retired cut-over machinery)
    "deep_nesting_functions": 6,
    "route_layer_imports": 0,
    "service_public_no_private": 5,  # +1 批7 ledger_has_any_expense — a one-query lifetime existence probe has no private helpers to call; the counter's pass-through heuristic matches its shape, banked as legitimate
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
    "unreferenced_modules": 218,  # −2 ADR-0049 web 面 slice 2a (web_debts 直接 import ledger_service+debt_service helpers → referenced, bank improved-INFO); +3 ADR-0049 §杠杆③ slice 3a (routes.repayment_drafts + schemas._repayment_drafts + debt_service._repayment_draft — covered via /api/repayment-drafts route tests + debt_service.__init__ re-export, not direct submodule-path import); +2 ADR-0043 tag_management_service + tag_undo_service (covered via /api/tags route tests, not direct import); +2 slice C web_tags + owner_console._tag_cleanup (HTTP-tested, not direct import); −15 PG-only slice 2 (retired _migrations/ + _validate/ submodules); −1 slice 5 (retired cut-over modules); −4 ratchet tightens on the gate's own improved-INFO (2026-06-11, 2026-06-12 ×3 — 批14 retiring web_stats, 扫尾W2 list_sent_for_expense wired); +6 ADR-0049 slice 1 Debt domain (models.debt / routes.debts / schemas._debts / debt_service._create+_query+_fold — covered via /api/debts route tests + test_debt_fold service imports, not direct submodule-path import); +6 ADR-0049 slice 2 Debt fact-write submodules (debt_service._serialize+_money+_guards+_repayment+_adjustment+_void — re-exported via debt_service.__init__ + exercised via /api/debts/{id}/repayments|adjustments|repayment-voids|void route tests, not direct submodule-path import); +1 ADR-0049 slice 3 debt_service._proposal (re-exported via debt_service.__init__ + exercised via /api/debts/{id}/repayment-proposals route tests, not direct submodule-path import); +1 ADR-0049 slice 6 goal_debt_repayment_service (re-exported via goal_service facade + exercised via /api/goals debt routes, not direct submodule-path import); +1 ADR-0049 slice 8e-3 debt_service._forgive (re-exported via debt_service.__init__ + exercised via /api/debts/{id}/forgive route tests, not direct submodule-path import) — APPROX, orchestrator finalizes
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
    "mutate_token_carriers": 59,  # +1 ADR-0049 §杠杆③ slice 3a POST /api/repayment-drafts/{id}/confirm carries expected_row_version (records a Repayment on the chosen Debt — fold-changing) — auto-detected carrier; +1 ADR-0049 slice 8e-6c POST /api/goals/{id}/target-date carries expected_row_version (payoff-deadline setter — bumps row_version ONLY, not goal_version) — auto-detected carrier; +4 ADR-0049 slice 2 fold-changing facts carry expected_row_version: POST /api/debts/{id}/repayments|adjustments|repayment-voids|void (§2.1 stale-intent fence + §3.6 fingerprint); +1 ADR-0049 slice 3 CONFIRM proposal carries expected_row_version (fold-changing) — auto-detected carrier; +1 ADR-0049 slice 6 POST /api/goals/{id}/debt-links carries expected_row_version (link replace bumps goal row_version + goal_version) — auto-detected carrier; +1 ADR-0049 slice 6 §6/F13 POST /api/goals/{id}/integrity-review/acknowledge carries expected_row_version (records keep-for-audit ack against goal_version) — auto-detected carrier; +1 ADR-0049 slice 8e-3 §3.7/§4 POST /api/debts/{id}/forgive carries expected_row_version (creditor forgiveness is fold-changing → cleared) — auto-detected carrier
    "mutate_token_exempted": 115,  # +2 ADR-0049 §杠杆③ slice 3a (POST /api/repayment-drafts create_row + POST /api/repayment-drafts/{id}/dismiss terminal_flag_flip; the DOWN-ratchet ``_ADR_0049_EXEMPTED_GRANDFATHER`` is re-pointed 113 -> 115). −2 PG-only slice 5 (retired /owner/migration-readiness cut-over + pre-v1-backup exemptions); +1 ADR-0049 slice 1 POST /api/debts create; +3 ADR-0049 slice 3 proposal create + withdraw + reject (NOT fold-changing → no expected_row_version; the DOWN-ratchet ``adr_0049_exempt`` exception is exact: base 110 -> current 113 only)
    "mutate_token_reason_admin_single_writer": 9,
    "mutate_token_reason_append_only_fact": 4,
    "mutate_token_reason_batch_db_write": 19,
    "mutate_token_reason_create_row": 29,  # +1 ADR-0049 §杠杆③ slice 3a POST /api/repayment-drafts (NLS repayment capture); +1 ADR-0049 slice 1 POST /api/debts; +1 ADR-0049 slice 3 POST /api/debts/{id}/repayment-proposals
    "mutate_token_reason_enqueue_task": 0,  # −1 PG-only slice 5 (cut-over was the only enqueue_task route)
    "mutate_token_reason_external_side_effect": 4,  # −1 PG-only slice 5 (retired pre-v1-backup)
    "mutate_token_reason_governance_action": 8,
    "mutate_token_reason_read_only_compute": 3,
    "mutate_token_reason_session_rotation": 5,
    "mutate_token_reason_terminal_flag_flip": 26,  # +1 ADR-0049 §杠杆③ slice 3a POST /api/repayment-drafts/{id}/dismiss (latches a captured draft dismissed); +2 ADR-0049 slice 3 proposal withdraw + reject (terminal status flip; not fold-changing)
    "mutate_token_reason_upsert_bucket": 8,
    # +1 PR-A (/web recurring); +7 PR-B income_plan OCC; +4 PR-C bill_split
    # accept atomic-claim; +8 ADR-0041 Slice A row_version groundwork; +3
    # ADR-0041 self-describing items/splits responses (parent row_version in
    # items-replace, acknowledge-mismatch, splits-replace responses); +12 ADR-0042 Slice A idempotency helper tests; +5 Slice B PATCH idempotency tests; +12 Slice D-1 state-machine idempotency tests; +15 Slice D-2 rules/aliases/items idempotency tests (header-required×5, committed-but-unseen rule+items+alias, delete HIT rule+alias, in-progress×2, reuse×2); +5 Slice E-1 splits-replace idempotency tests (header-required, committed-but-unseen, stale-409, in-progress, reuse); +5 Slice E-2 recognize-text idempotency tests (same shape); +1 ADR-0042 tags-guard hardening (explicit {"tags":null} no longer clobbers); +10 Slice F goals/income-plan PATCH idempotency tests (header-required×2, committed-but-unseen goal+plan, stale-409×2, in-progress×2, reuse×2). +1 owner-console live DB dialect readiness test (ADR-0041 cut-over visibility). +11 ADR-0027 Frankfurter transport + weekend fallback + owner FX panel tests (parse×4, dispatcher, weekend-resolve, pre-history pending, run_once×2, owner 403 + manual refresh); +1 mutate exempt /owner/fx/refresh (upsert_bucket); +2 FX review follow-up (ecb dispatcher branch + run_fx_sync_once unexpected-error). +4 ADR-0043 slice A (legacy tags management-columns + snapshot-tables migration ×1; expense_tags mirror reconcile relink / orphan-removal / noop-idempotent ×3). +4 ADR-0043 slice A review follow-up (alembic ALTER-branch round-trip migration ×1; reconcile occ-effective-bump / unrelated-not-bumped / multi-batch ×3). +20 ADR-0043 slice B (tag management: 13 test_tag_management list/rename/delete/merge/viewer/isolation/auth/read-filter/self-merge/dedup + 7 test_tag_undo undo-restore/stale-409/partial-CAS/merge-undo/window-404/unknown-404/purge). +14 ADR-0043 slice C tag-mgmt UI (+7 test_web_app_tags, +3 test_owner_tag_cleanup, +4 route-inventory writer-only parametrize for the 4 /web/tags POST routes). +1 slice C follow-up (owner orphan-cleanup TOCTOU re-check skips a re-used tag). +3 ADR-0043 codex-review P1 (test_web_session_write_gate: web-session viewer write-gate × viewer-denied/member-allowed/not-listed-denied). +3 ADR-0043 review-2 (test_tag_management merge-id-order + orphan-guard service tests ×2; web_tasks cancel joins writer-only route-inventory parametrize ×1). +1 ADR-0043 review-3 (test_tag_management: _claim_merge_pair on a concurrently soft-deleted tag surfaces state_conflict 409, not tag_not_found 404). +1 ADR-0043 review follow-up (OpenAPI API/UploadLink error responses use project ErrorResponse, not HTTPValidationError). +4 ADR-0045 CSRF signing key (csrf_key_service get-or-create idempotent + non-placeholder; _csrf_secret prefers real env, rejects placeholder → per-install app_meta key; persisted key covers placeholder env on /web vs genuine-no-key fail-closed 500). +3 ADR-0045 follow-up (budget-advisor audit input-hash HMAC: per-install audit key rejects placeholder + is csrf-separated; compute_input_hash uses it; prefers a real env secret).
    "backend_pytest_count": 1813,  # +39 ADR-0049 Debt slice 2 fold-changing facts (test_debt_repayment ×16: F6 reduce-once / clear-latches-cleared / F7 idem-replay-applies-once / distinct-keys-not-deduped / same-key-diff-fingerprint-reused / F8 over-remaining-rejected (fresh + after-partial) / amount<=0-422 / missing-idem-key-422 / stale-version-409 / missing-debt-404 / viewer-403 / unauth-401 / fx-paid_at-snapshot-freezes-home-cents / fx-pending-409; test_debt_repayment_concurrency ×2: two-sessions FOR UPDATE lock-contention + two-sessions serialize-then-second-rechecks-overpay (real_db); test_debt_adjustment ×10: positive-raises / negative-lowers / cannot-drive-remaining-negative-422 / exact-zero-clears / reason-required-422 / idem-replay-once / viewer-403 / unauth-401 / stale-version-409; test_debt_void ×11: void-repayment-reopens+keeps-row(F10) / void-repayment-twice-already-voided-409 / unknown-repayment-404 / cross-debt-repayment-404 / void-debt-latches-voided+drops-open-total / void-debt-twice-already-voided-409 / voided-debt-rejects-further-repayment-409 / void-debt-reason-required-422 / void-debt-idem-replay-once / viewer-403 / both-void-routes-unauth-401). +2 audit gate 0049 ratchet exception pins (109→110 allowed, 110→111 still fails). +14 ADR-0049 Debt slice 1 (test_debts ×11 create-external/member/list-scope/get+cross-404/viewer-403/fx-pending-409/fx-frozen/extra-forbid/idem-key-required/401/idem-replay+mismatch; test_debt_fold ×3 empty-facts remaining==principal/paid==0/principal-frozen). +3 audit helper hardening (outbox AppContainer parser regression + release-audit compact success/failure behavior); −5 PG-only slice 4 (backup-validation reroute): dropped 2 backup-dialect-dispatch tests + 1 legacy restore_database delegation test + collapsed 3 SQLite-fixture owner-backup tests into 1 .dump test (slice 2 set 1626 from 1686); −19 slice 5 (retired test_owner_console_migration_readiness + test_v1_cutover cut-over tests + most of test_data_migration; rescued surviving coverage — 4 app_meta tests → test_app_meta_service, 1 timestamptz schema invariant → test_schema_invariants); +2 debt #2 extra="forbid" sweep (test_request_model_forbid: every *Request model forbids extras ratchet + pair 422-on-unknown-field e2e); +1 backup-chain fix (find_pg_binary Windows install-glob fallback test — nightly task had failed validation on pg_restore discovery); +6 audit-P2 bill-split CAS+FX (two-session reject/cancel-vs-accept races ×2, two-session _mark_expired guard, accept-after-TTL 410, sweeper expires-overdue + spares-accepted ×2; the USD snapshot test was rewritten in place to pin home-currency landing, ±0); +9 audit-P2 /web batch (bill-split TOCTOU/duplicate-invite flash ×2, import bad-encoding + unknown-batch flash ×2, edit missing-expense full-page redirect + drawer-fragment HTML ×2, month-picker drops page ×1, source-label real-value map + breakdown label-aggregation ×2); +2 ci-gap scanner hardening (blank line must not unmute an if:false step; gradle prose/echo mention must not satisfy the pins); +4 audit-P3 /web batch (inbox accept-dropdown shows ledger NAME + accounting-tz times, sent-page local time ×2; error-code-table lane real-tree pass + bite check ×2); +1 ops-review P3 #8 (find_pg_binary numeric install sort — a lingering 9.6 client must not beat 17 by string order); +4 web-review P2 #6 (edit POST error paths flash-redirect when the re-read row vanished: save→confirmed, confirm AppError + stale-token, reject — previously escaped as bare JSON); +4 web-review follow-up (items/splits sub-forms join the vanished-row guard via the shared helper: items save, items acknowledge ×2 incl. stale-token, splits save); +12 audit-pool web/owner sweep (six-month trend-card container ×1 — split into its own test, the inline assertions had pushed the big reports test past the 80-line debt line; orphan-page inbound links ×1, drawer default-submit shim + reject data-confirm ×1, dashboard/donut static wiring ×1, owner upload-links tutorial pins duplicate branch ×1, backup_health service fresh/stale/missing ×3, owner index stale red-banner + fresh no-banner ×2, backups page stale banner ×2; empty-state/iPhone-copy assertions extended in-place ±0); +3 error-copy three-surface lane (real-tree pass + bite + comment-aware); +4 owner upload-link handoff batch (reveal card copy-button + QR markers with URL still single-instance, no-PUBLIC_BASE_URL branch hides handoff UI, vendored qrcode.js/LICENSE self-hosted + defer order, expiring-soon badge-warn countdown + 续期 label); +2 UI/UX 批7 /web 首日引导 (dashboard first-day branch shows 3 entry links until first lifetime expense + steady title after ×1, pending empty-cell filter=all offers upload-links/CSV entry links vs filtered-empty has none ×1); +4 UI/UX 批1 /web 编辑补全 (expense_time datetime-local round-trips Beijing wall-clock to UTC + prefill ×1, bad time flashes and leaves row untouched ×1, tags save + empty-string clears ×1, category datalist renders used+default incl. drawer ×1); +14 UI/UX 批10 /web 复核流水线 (test_web_review_flow ×12: fragment success/error 422/vanished 404/return_to no-JS queue/OCC refresh/template pins; test_web_duplicates +2 keep-fragment); ±0 UI/UX 批14 stats→reports IA 归并 (deleted the 3 /web/stats page tests with the page; +1 re-pointed smoke test_web_reports_local_returns_200, +1 insight-degrade coverage migrated to /web/recurring as test_web_recurring_candidate_insight_failure_degrades, +1 top-expenses/seg assertions split out of the 80-line debt test as test_web_reports_absorbs_stats_top_expenses_and_seg_controls per the #49 lesson — tag-filter coverage already equivalent on /web/confirmed; net ±0); +9 扫尾W2 /web 拆账发起表单+行制 (test_web_bill_split 8→17: render-state ×3 incl. viewer-hidden, no-member guide ×1, POST success + exceed flash ×2, sent-rows + cancel ×1, row-craft both pages ×1, member-source field ×1); +3 扫尾W3 dashboard 进度条 (payload top3 + 模板进度标记 + 超限态, test_web_app_dashboard ×3); +12 扫尾G4 /web+/owner HTML 错误页 (404/500/403/422 双形态 + /api 硬保证, test_web_error_pages ×12); +3 轴6 备份健康字段 (status/private 报 latest_backup_at/backup_age_hours/backup_stale, 复用 backup_health() 48h 单源阈值; 有备份字段就位 + 无备份 stale=True + backup_health 异常降级, test_status_private ×3); +52 ADR-0049 slice 3 MemberRepaymentProposal (split by concern: lifecycle/auth/FX/idempotency/concurrency; includes create/supersede/explicit supersede target/stale replacement guard/withdraw/confirm-full+partial/reject lifecycle, debtor/creditor/viewer/unauth guards, idempotency replay/reuse/missing/cross-debt/cross-actor, FX freeze, pending-rate, overpay/no-clobber, and 3 real_db concurrency tests). +1 ADR-0049 slice 3 migration-immutability fix (test_alembic_debt_idempotency_unique_migration round-trips 20260614_0003: forward DROP of the 4 fact-table global idempotency_key uniques + downgrade re-add; 20260614_0001 restored to its merged form rather than edited in place — uniqueness is tenant-scoped in api_idempotency_keys per §3.6). +1 ADR-0049 slice 3 foreign-amount fingerprint canonicalization (test_create_proposal_foreign_amount_idempotent_across_minor_unit_rounding: a USD 10.004 lost-response retry HITs the same 10.00 proposal — the create fingerprint hashes the stored minor-unit amount via amount_major_to_minor, not the raw major-unit Decimal)
    # Android ``@Test`` count is enforced separately by the Android CI
    # lane (``:app:assertAndroidTestCountEqualsBaseline`` gradle task against
    # ``android/audit/test_count_baseline.txt``). Cross-job coordination
    # is intentionally avoided — each side enforces its own contract,
    # at the cost of cut-over PRs that touch both sides needing to
    # update both baseline files. Android count is NOT listed here.
}

STRICT_EQUALITY_BASELINE["backend_pytest_count"] = 1994  # +1 ADR-0049 债务域 web 面 slice 1B premium + IA 移 (test_web_debts +1: _amount_segments cur/int/dec 拆分〔CNY 小数 / JPY 无小数〕; 既有用例就地扩断言——列表/详情 editorial 英雄 spans + 外部删重复「剩余」行 + paid/principal businesslike 条, ±0 node). +6 ADR-0049 债务域 web 面 slice 2a read-only /web/debts/{id} 详情按角色分轴 (test_web_debts +6: external 详情 summary〔剩余/本金/已偿还/应付〕/ member 详情 communal〔一起处理+看看账+这件事一共, 无应付应收剩余 danger〕/ unknown→404 / _member_headline 矩阵全分支+near-ratio 边界 / _communal_ratio 钳位 / _detail_view 成员 neutral+voided 永不 danger+外币 FX 回退外部卡+外部 voided danger). +8 ADR-0049 债务域 web 面 slice 1 read-only /web/debts list (test_web_debts ×8: remote-403 / empty-renders / external-i_owe-open row〔name+应付+未结清+amount〕/ owed_to_me→应收 / full-repay→已结清+dt-pill-ok+zero-remaining / void→已作废+dt-pill-danger / member bill_split debt renders 家庭成员+应付+未结清〔neutral index mirrors Android list〕 / _debt_view unit: direction+status labels/tones + member/external fallbacks). +9 ADR-0049 #4 debt-domain DB constraint backstops: test_alembic_debt_constraint_hardening_migration ×1 (3 FK + 3 status<->committed CHECK round-trip on real PG, asserting migration-built defs structurally EQUAL the ORM〔referent/predicate, not just name〕; circular-FK use_alter proven by create_all) + test_debt_constraint_enforcement ×8 (mrp committed CHECK rejects confirmed-without-committed AND committed-on-pending〔both directions〕 / confirmed_amount CHECK / all 3 FKs reject orphan〔committed_repayment, repayments.proposal_id, self-ref supersedes〕 / RepaymentDraft committed CHECK both directions — the migration ADD CONSTRAINT fails fast on dirty data). +18 ADR-0049 §杠杆③ slice 3b ephemeral suggested-Debt match (test_repayment_draft_match ×12 pure matcher: unique-feasible-label-match / containment-either-direction / casefold+whitespace-normalize / exact-beats-contains / ambiguous-equal-strength→None / specific-merchant-no-match-does-NOT-fall-through / blank-merchant-single-feasible-suggests / blank-merchant-multiple→None / infeasible-amount-excluded / feasibility-filter-precedes-ambiguity / empty-candidates→None / [6-lens review] containment-class-jump-on-multi-keyword-label documented-tradeoff; test_repayment_drafts list ×5: pending-draft-carries-suggested_debt_public_id / ambiguous-two-花呗→None / only-pending-not-resolved / [6-lens review] service-unfiltered-status=None-list-suggests-only-pending〔the per-draft pending guard, unreachable via the always-single-status route〕 / [6-lens review] excludes-non-repayable-shapes〔voided+member+bill_split candidate-query WHERE exclusions each bite〕; test_repayment_drafts_isolation ×1: suggestion candidate query tenant-scoped — owner's 花呗 draft never suggested ledger-B's 花呗 Debt). +31 ADR-0049 §杠杆③ slice 3a NLS repayment-capture inbox (capture pending/dedup-by-identity/distinct-identities/invalid-source-422/home-currency-server-set/viewer-403/unauth-401; list pending+status-filter; confirm records-once+reduces-remaining / clears-debt / overpay-422-draft-stays-pending / member-debt-409 / stale-debt-version-409 / missing-debt-404 / missing-draft-404 / idempotent-replay-records-once / missing-idem-key-422 / already-confirmed-new-key-409 / viewer-403 / unauth-401; dismiss latches / idempotent-when-already-dismissed / confirmed-draft-409 / viewer-403 / unauth-401; two-sessions confirm serializes-on-draft-row[real_db] + serialize-then-second-rechecks[real_db]; +4 from 6-lens review: home_currency_code dropped from the create request + set server-side〔currency finding: a field whose only legal value is the constant home currency〕 / dismiss viewer-403 / cross-ledger draft isolated〔confirm+dismiss+list 404/excluded〕 / cross-actor confirm replay→idempotency_key_reused〔actor-scope fingerprint〕; test_alembic_repayment_drafts_migration ×1 create-table round-trip reflects columns/CHECKs/unique/indexes[real_db]; +1 codex PR#22 review: confirm records Repayment.paid_at = draft.captured_at〔captured payment time〕 not review-time now()). +7 ADR-0049 slice 8e-6d suppress-on-stale floor (杠杆④, test_debt_repayment_goal_kpi: stale-suppresses-date-and-surfaces-days-since / fresh-when-recent-activity-keys-off-latest-fact-not-debt-age / strict->threshold-boundary / wire-e2e-days_since_last_activity-not-projection; +3 from 6-lens review: multi-debt-freshly-linked-debt-does-NOT-reset-staleness〔P2 fact-based not created_at〕 / fresh-counts-recent-forgiveness〔latest_fact_at forgive branch〕 / latest_fact_at-spans-types-void-latest+none-without-facts〔void branch + None path〕; the prior 8 projection tests adapt to the new 3-tuple compute_external_kpi return and pin days_since None on the none/fresh shapes). +2 codex PR#20 P1/P2 通知草稿每次投递身份去重 (test_distinct_notification_keys_with_identical_content_each_create_a_draft: 两条不同投递身份 + 同内容 → 2 草稿、同身份重发 → 去重, idempotency 键以 notification_key 为主轴; test_long_notification_key_is_accepted_not_rejected: 长 key 不 422——cap 是 DoS 界非 fit 界, 值无论多长都会被 hash 进 idempotency 材料, P2#2). +15 ADR-0049 slice 8e-6c payoff DEADLINE + three-state (test_debt_goal_target_date ×14: payoff_three_state pure month-compare ×1 [ahead/at_risk/on_track/None×2]; create-time target_date echoed ×1; spending-goal rejects target_date 422 ×1; three_state ahead far-future / at_risk past / suppressed-no-projection / member-None ×4; setter set+clear / bumps-row_version-NOT-goal_version / on-achieved-goal-stays-achieved〔CRITIQUE-2: no silent un-achieve〕 / stale-409 / requires-auth-401 / viewer-403 / idempotent-replay ×7; test_alembic_goal_target_date_migration ×1 add-column round-trip[real_db]). +17 ADR-0049 slice 8e-6b external-debt payoff projection (test_debt_repayment_goal_kpi ×17: project_payoff_days pure-math ×2 [observed-pace / suppress-thin-zero-no-reduction]; compute_remaining_as_of fold ×4 [all-fact-types-at-now equals full fold / excludes-facts-recorded-after-cutoff / zero-when-debt-newer-than-cutoff / excludes-repayment-voided-during-window〔team-review P3: subtlest RepaymentVoid.created_at<=cutoff branch〕]; velocity ×4 [repayment-pace / writeoff-NEGATIVE-adjustment-not-just-repayments〔CRITIQUE-1#1 blocker: write-off shows real velocity〕 / windows-on-created_at-NOT-paid_at〔CRITIQUE-2 blocker: recording cadence not back-dateable〕 / accounting-tz-today-midnight]; suppression ×3 [mixed-currency / thin-window<14d / no-paydown]; §4 server-gating ×4 [member-None / mixed-None / pure-external-populated-e2e / all-voided-None]); +15 ADR-0049 slice 8e-3 §3.7/§4 creditor forgiveness (test_debt_forgive ×15: full-open forgive→cleared+is_forgiven / forgive-after-partial-repayment fold==0 with forgiveness=remaining_before / repayment-cleared is_forgiven=False / debtor-403 / external-409 member-only / already-settled-409 zero-remaining / stale-version-409 OCC / non-participant-404 existence-hiding / cross-ledger creditor forgives shell-redacted / idempotent-replay one fact / actor-scoped-fingerprint-422 (diff actor can't HIT past creditor guard) / supersedes-pending-proposal §4 F5 / requires-idem-key-422 / requires-auth-401 / §6-F13 goal-linked forgive stays achieved without review). +1 ADR-0049 slice 8d viewer_is_debtor server-authoritative role (test_member_repayment_proposal_cross_ledger::test_viewer_is_debtor_role_for_both_parties — debtor reads True / cross-ledger creditor reads False; the shared-ledger creditor reading False despite a non-null ledger_id is an inline assertion added to the existing settles_debt test). +8 ADR-0049 slice 6 §6/F13 integrity-review (debt-void-after-achievement → achieved+needs_review, reopen decoupled; acknowledge keep-for-audit carrier): evaluator +2 (ack-clears + ack-not-carried-across-version-bump pinning the per-version INT scoping vs a one-shot bool; debt-void-forces-review test renamed); lifecycle +6 ack guards (auth-401 / requires-idem-key-422 / stale-409 / rejects-not-yet-achieved-422 / no-pending-review-422 / idempotent-replay). +1 ADR-0049 slice 3 paid_at FX-date fingerprint regression; +6 ADR-0049 slice 4 bill_split→Debt linkage (test_bill_split_debt_linkage: accept-creates-member-Debt rollout-on / no-Debt rollout-off / re-accept-no-duplicate / reject-no-Debt / foreign-parent-stays-home-shape / debt-failure-rolls-back-whole-accept[real_db]); +8 ADR-0049 slice 5 account-scoped cross-ledger participant confirm/reject §5.2 (test_member_repayment_proposal_cross_ledger ×6: non-member creditor confirms+clears with shell-redacted ledger_id / non-member creditor rejects / non-member creditor lists pending proposal / member creditor in shared ledger settles keeping ledger_id / non-participant existence-hiding 404 on read+list+confirm / cross-ledger confirm idempotent replay; test_bill_split_debt_linkage ×2: two-sessions concurrent accept creates single Debt[real_db] / duplicate uq_debts_source rejected); +28 ADR-0049 slice 6 debt_repayment goal §6 (test_debt_repayment_goal ×12 evaluator [incl. achieved-version-stays-achieved-after-linked-debt-voided pinning the §6/F13 latch-wins ratification]; in_progress / all-cleared-achieves+latches-once / one-open / voided-not_evaluable+review / replace-bumps-version+freezes-old-set / unlink-open-achieves-new-version-not-old / achieved-then-reopen-stays-achieved / viewer-read-computes-achieved-without-latching / not_evaluable-recovers-via-link-replace / debt-vs-spending-list-isolation / spending-limit-regression; test_debt_repayment_goal_lifecycle ×15 guards: replace requires-auth-401 / idempotent-replay / stale-409 / requires-idem-key-422 / rejects-empty-set-422 / unknown-debt-404 / reject-spend-fields / requires-≥1-debt / unknown-debt-404-create / cross-ledger-isolation / viewer-403-create+replace / patch-rejects-debt-goal / two-active-debt-goals-coexist / replace-rejects-spending-goal / archive-hides; test_alembic_goal_debt_repayment_migration ×1 widen-goals round-trip[real_db] incl. scope-index goal_type predicate assertions) — 6-lens adversarial review fixed P1 archive_goal debt dispatch (int(None) 500) + P2/P3 coverage (two-goals-coexist, viewer-read-no-latch, not_evaluable-recovery, replace-rejects-spending, debt-links 401, migration scope-index predicate)


# UP-only keys cannot drop vs base; strict equality alone could miss lockstep
# baseline/actual reductions. ``backend_pytest_count`` is strict-only.
BASELINE_RATCHET_UP: frozenset[str] = frozenset({
    "mutate_token_carriers",
})

# DOWN-only keys may shrink as routes graduate; they must not grow back.
# New ALLOWLIST routes need explicit ADR pointers per v1.3 PR-2.
BASELINE_RATCHET_DOWN: frozenset[str] = frozenset({
    "mutate_token_exempted",
})
_ADR_0049_EXEMPTED_GRANDFATHER = (113, 115)  # §杠杆③ slice 3a re-points the single in-flight DOWN-ratchet hop 113->115 (repayment-draft create_row + dismiss terminal_flag_flip, each with a ledger entry + ADR pointer); the prior 110->113 hop is dead history (main sits at 113).

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
      1. ``GITHUB_BASE_REF`` (the CI runner sets this on PR events to
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
    """True when running in PR CI (``GITHUB_BASE_REF`` set). Distinguishes
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
        adr_0049_exempt = key == "mutate_token_exempted" and (
            base_val, current_val
        ) == _ADR_0049_EXEMPTED_GRANDFATHER
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
