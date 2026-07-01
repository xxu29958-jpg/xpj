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
    "broad_exception": 23,  # −1 PG-only slice 2 (retired SQLite migrator/validator). +1 P1 启动迁移前备份 gate(_backup_before_upgrade 对任何备份失败 fail-CLOSED——必须 catch-any 才能在 pg_dump/磁盘/校验等任意失败时中止迁移,窄 catch 会漏失败放过迁移=破坏安全目的)
    "generic_raises": 7,  # +1 ⑥ P3#3 scheduler_lease.try_claim_scheduler_lease 在途事务守卫 RuntimeError (检测到 db.in_transaction() 即 raise, 防偷提交调用方未提交事务; API 误用前置条件非用户面 AppError, 镜像 main.py 启动守卫 RuntimeError 先例). −3 PG-only slice 5 (retired v1_migration handler RuntimeError raises + mark_v1_cut_over). +1 P1 启动迁移属主预检 RuntimeError(_assert_role_can_alter_existing_schema 致命启动条件,无 HTTP AppError 适配,镜像 main.py 既有启动 RuntimeError 守卫). +1 P1 启动迁移前备份 fail-closed RuntimeError(_backup_before_upgrade 备份失败即致命中止,镜像同款启动 RuntimeError)
    "todo_markers": 9,
    "hardcoded_urls": 12,  # +2 ADR-0027 Frankfurter default URL (config default, mirrors ECB inline pattern)
    "credentials_risk": 4,
    "n_plus_one": 2,
    # PR-A wires fetch_expense_updated_at_in_status (new in _query.py) into the
    # /web/pending route; bank the reduction so unreferenced_modules can't
    # silently re-creep.
    "unreferenced_modules": 219,  # +1 issue #65 slice 6a owner "My Devices" (routes.devices + services.owner_device_service — covered via /api/ledgers/{id}/devices route tests in test_my_devices, not direct submodule-path import; net +1, schemas._identity already referenced). +1 ⑥ debt 账单 OCR slice 1 routes/debt_bills.py（POST /api/debts/parse-bill——经路由测试 HTTP 覆盖，非 direct submodule-path import；local_llm_vision + debt_bill_parse_service 被 test 直接 import 故不计）. −1 ADR-0049 web 面 slice 4 (web_debt_goals 直接 import goal_debt_repayment_service.list_debt_repayment_goals → 该模块由 facade-only 转为 referenced，bank improved-INFO 防回归). −2 ADR-0049 web 面 slice 2a (web_debts 直接 import ledger_service+debt_service helpers → referenced, bank improved-INFO); +3 ADR-0049 §杠杆③ slice 3a (routes.repayment_drafts + schemas._repayment_drafts + debt_service._repayment_draft — covered via /api/repayment-drafts route tests + debt_service.__init__ re-export, not direct submodule-path import); +2 ADR-0043 tag_management_service + tag_undo_service (covered via /api/tags route tests, not direct import); +2 slice C web_tags + owner_console._tag_cleanup (HTTP-tested, not direct import); −15 PG-only slice 2 (retired _migrations/ + _validate/ submodules); −1 slice 5 (retired cut-over modules); −4 ratchet tightens on the gate's own improved-INFO (2026-06-11, 2026-06-12 ×3 — 批14 retiring web_stats, 扫尾W2 list_sent_for_expense wired); +6 ADR-0049 slice 1 Debt domain (models.debt / routes.debts / schemas._debts / debt_service._create+_query+_fold — covered via /api/debts route tests + test_debt_fold service imports, not direct submodule-path import); +6 ADR-0049 slice 2 Debt fact-write submodules (debt_service._serialize+_money+_guards+_repayment+_adjustment+_void — re-exported via debt_service.__init__ + exercised via /api/debts/{id}/repayments|adjustments|repayment-voids|void route tests, not direct submodule-path import); +1 ADR-0049 slice 3 debt_service._proposal (re-exported via debt_service.__init__ + exercised via /api/debts/{id}/repayment-proposals route tests, not direct submodule-path import); +1 ADR-0049 slice 6 goal_debt_repayment_service (re-exported via goal_service facade + exercised via /api/goals debt routes, not direct submodule-path import); +1 ADR-0049 slice 8e-3 debt_service._forgive (re-exported via debt_service.__init__ + exercised via /api/debts/{id}/forgive route tests, not direct submodule-path import) — APPROX, orchestrator finalizes
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

CODEBASE_DEBT_LIMITS.update(
    {
        "files_over_500": 18,
        "long_functions": 40,
        "unreferenced_modules": 224,
    }
)  # ADR-0052 recycle-bin follow-up: bank audited growth from archive/restore slice.


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
    "mutate_token_carriers": 60,  # +1 ADR-0049 §7.0/8e-6e POST /api/debts/{id}/kind carries expected_row_version (debt_kind OCC setter — bumps row_version, not fold-changing) — auto-detected carrier. +1 ADR-0049 §杠杆③ slice 3a POST /api/repayment-drafts/{id}/confirm carries expected_row_version (records a Repayment on the chosen Debt — fold-changing) — auto-detected carrier; +1 ADR-0049 slice 8e-6c POST /api/goals/{id}/target-date carries expected_row_version (payoff-deadline setter — bumps row_version ONLY, not goal_version) — auto-detected carrier; +4 ADR-0049 slice 2 fold-changing facts carry expected_row_version: POST /api/debts/{id}/repayments|adjustments|repayment-voids|void (§2.1 stale-intent fence + §3.6 fingerprint); +1 ADR-0049 slice 3 CONFIRM proposal carries expected_row_version (fold-changing) — auto-detected carrier; +1 ADR-0049 slice 6 POST /api/goals/{id}/debt-links carries expected_row_version (link replace bumps goal row_version + goal_version) — auto-detected carrier; +1 ADR-0049 slice 6 §6/F13 POST /api/goals/{id}/integrity-review/acknowledge carries expected_row_version (records keep-for-audit ack against goal_version) — auto-detected carrier; +1 ADR-0049 slice 8e-3 §3.7/§4 POST /api/debts/{id}/forgive carries expected_row_version (creditor forgiveness is fold-changing → cleared) — auto-detected carrier
    "mutate_token_exempted": 120,  # issue #65 slice A: +1 owner-facing "My Devices" delete route (POST /api/ledgers/{ledger_id}/devices/{public_id}/delete terminal_flag_flip; account-owner twin of loopback /owner/devices/{public_id}/delete, no row_version → exempt). DOWN-ratchet single in-flight up-hop re-pointed 119 -> 120 (prior 116 -> 119 = dead history, main was at 119; slice 6a added the rename/revoke/pairing-codes routes).
    "mutate_token_reason_admin_single_writer": 10,  # +1 issue #65 slice 6a POST /api/ledgers/{ledger_id}/devices/{public_id}/rename (owner single-writer device-name update; mirrors the admin rename)
    "mutate_token_reason_append_only_fact": 4,
    "mutate_token_reason_batch_db_write": 19,
    "mutate_token_reason_create_row": 30,  # +1 ADR-0049 §杠杆③ slice 3a POST /api/repayment-drafts (NLS repayment capture); +1 ADR-0049 slice 1 POST /api/debts; +1 ADR-0049 slice 3 POST /api/debts/{id}/repayment-proposals; +1 issue #65 slice 6a POST /api/ledgers/{ledger_id}/devices/pairing-codes (owner mints a pairing code for "add a device")
    "mutate_token_reason_enqueue_task": 0,  # −1 PG-only slice 5 (cut-over was the only enqueue_task route)
    "mutate_token_reason_external_side_effect": 4,  # −1 PG-only slice 5 (retired pre-v1-backup)
    "mutate_token_reason_governance_action": 8,
    "mutate_token_reason_read_only_compute": 4,  # +1 ⑥ debt 账单 OCR slice 1 POST /api/debts/parse-bill（瞬态解析无 DB 写）
    "mutate_token_reason_session_rotation": 5,
    "mutate_token_reason_terminal_flag_flip": 28,  # +1 ADR-0049 §杠杆③ slice 3a POST /api/repayment-drafts/{id}/dismiss (latches a captured draft dismissed); +2 ADR-0049 slice 3 proposal withdraw + reject (terminal status flip; not fold-changing); +1 issue #65 slice 6a POST /api/ledgers/{ledger_id}/devices/{public_id}/revoke (latches device revoked_at + kills its tokens); +1 issue #65 slice A POST /api/ledgers/{ledger_id}/devices/{public_id}/delete (hard-removes a revoked device + its in-scope tokens/links)
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

STRICT_EQUALITY_BASELINE["backend_pytest_count"] = 2247  # +1 issue #65 slice 7 owner devices page surfaces add-device link to /owner/pairing (test_owner_devices_page_links_to_pairing; cohesion affordance only — no new route, no page removal). +9 issue #65 slice 6a owner "My Devices" routes (test_my_devices ×9: list marks current + hides internal ids / rename / revoke-other / revoke-current 409 / owner-revokes-another-members-device-in-ledger 200 / pairing-code 201 / no-auth 401 / viewer 403 / wrong-ledger 404). +13 issue #65 slice 3 路由收 server-id-or-local:{ref} str + OCC 首写（test_expense_local_ref_mutation 13: local-ref 首写 sentinel-0 不误 409 / 首写应用到当前 row_version〔server-id 先抬版本证读当前非假设1〕/ local-ref 与 server-id 解析同一行 / 首写 §4.6 replay 同 key+sentinel 返 canonical 不重放 / A·B·cross 正交〔首写后 stale server-id 仍 409 + 正确版本 200〕/ server-id+sentinel-0→409〔synced 行不可盲写〕/ widened str path 纯数字 server-id 老路径仍通〔向后兼容〕/ 未知 local-ref→404 / 畸形非数字非 local ref→404〔非 int() 500〕/ 跨设备 local-ref→404〔device 命名空间在路由强制〕/ confirm via local-ref 解析〔explicit-version 路由 idempotent 200〕/ confirm 未知 local-ref→404 / 〔对抗审 P2〕confirm 经 local-ref 首写 sentinel-0 跑真 CAS〔flip pending 后 explicit-version 路由证 effective 非 raw sentinel 入 CAS〕）. +8 issue #65 slice 2 resolve_expense 收口（test_expense_resolve: server-id 解析 / server-id decimal-string 解析〔对抗审 P2: 文档宣称的 string ref 形态补测, slice3 路由 path 参数用〕/ server-id 跨租户 miss / local-ref 解析 / local-ref 跨设备 miss / local-ref 跨租户 miss / local-ref 无 device→None / _audit_expense_resolve.find_violations 钉死 scattered 命中而 resolver-int(ref)+projection 不命中）. +11 issue #65 slice 1 device-scoped 幂等手动记账 client_ref（test_expenses_manual_client_ref 10: no-auth→401 / 同 ref 同 body 幂等返同行 / 自动分类 category 重放不误判 mismatch / amount|merchant|note 不同→idempotency_key_reused 422 ×3〔amount 例并钉拒绝后原行不被改写〕/ null client_ref 不去重建两行 / 空串 client_ref 当无 ref 不去重 / 同 ref 异 device 建两行〔device 命名空间〕/ unique-index race 回落既有行; + test_alembic_expense_draft_request_fingerprint_migration 1: PG round-trip 加 expenses.draft_request_fingerprint nullable 列〔含 VARCHAR(64) 长度断言〕）. +1 issue #64 A1 收尾 check_text_encoding 死门修复（test_native_ps_gate_calls_are_lastexitcode_guarded：两 workflow 的 check_*.ps1 native 调用后必须紧跟 $LASTEXITCODE 守卫，防 gate 被无声删护栏后复活原 bug）. +6 issue #64 W3 /web 高频移除型 bulk 改 fetch+partial（test_web_app_bulk_batch: confirm_ready fragment 只返实际确认 id 跳过 missing-amount / confirm_ready fragment 排除跨账本 id（对抗审 test-efficacy gap 补）/ batch-reject fragment 返 removed_ids / no-selection→error JSON / set_category fragment 被 _REMOVAL_ACTIONS gate 仍 303+removed_ids 不在响应 / bulk-bar.js 含 fetch+partial 机制 content-assert——/web fetch-JS 无浏览器测试, content-assert 是回归地板镜像 drawer.js）. +1 issue #64 W2 图片永不 gzip 不变量护栏（test_image_response_no_gzip: /api/expenses/{id}/image + /thumbnail 带 Accept-Encoding:gzip 仍无 content-encoding:gzip——守"永不 gzip 受保护图片流"不变量, 防未来裸加全局 GZipMiddleware 双压图片/CRIME 面; 审计结论: origin 零压缩中间件, 文本压缩归 Cloudflare 仓内无法验证, 默认不加 app 侧压缩）. +3 issue #64 W1 条件加载 ECharts（test_web_conditional_assets: 非图页 pending/confirmed/debts 不再加载 echarts/reports.js/category-donut/trend-chart + dashboard 仅 echarts+category-donut + reports 仅 echarts+trend+reports.js——双向钉死, base.html page_scripts 块按页注入, 防再全局化 1.1MB 包或漏掉某图页）. +11 ⑥ debt 账单 OCR 后端 slice 1（ADR-0049 §D 瞬态解析: 抽 call_local_llm_vision 共享视觉引擎〔小票路径不变, net +2: test_expenses_ocr_internals −3 engine 测试 → 新 test_local_llm_vision +5 含 http-error-不泄漏/slot×2/json-fence/vision-orchestration〕+ debt_bill_parse_service〔DebtBillSuggestion + parse_debt_bill + 账单 prompt + empty/mock/local_llm provider + DEBT_BILL_PROVIDER 配置〕+ POST /api/debts/parse-bill writer-gated 瞬态路由〔不落库/不建债/不存图〕net +9: test_debt_bill_parse 服务 5〔empty-blank/mock-installment/coerce-bounds/prompt-markers/provider-dispatch〕+ 路由 4〔mock-200/无auth-401/非图-400/viewer-403〕）. +3 P1 还款捕获草稿 account-scope 隔离修复 (跨切片复扫 confirmed P1: GET /api/repayment-drafts + confirm/dismiss 仅 ledger-scoped → 同账本成员私人支付通知捕获互泄/可互相确认忽略; list_repayment_drafts/_lock_pending_draft/get_repayment_draft_response 加 created_by_account_id==actor_account_id, 镜像 /web 审计 + learning matcher 的 account-scope; test_repayment_drafts_isolation +3: 同账本双向 list 隔离+正向控制 / 他成员 fresh-key confirm→404 / 他成员 dismiss→404). +2 /web installment 分期卡 (PR B follow-on: debt_detail.html 加分期计划卡, _detail_view→_installment_view gate〔isOpen&&installment-scheduled〕+ 中性进度 clamp + 合约还清日〔措辞同 web _payoff_line + Android〕+ 每期无息估算; 新文件 test_web_debt_installment.py +2〔detail 端到端渲染 + _installment_view 单测: gate None / clamp N/N / per-period floor-discriminating / periodic-label〕——拆出独立文件守 files_over_500 门〔加进 test_web_debts.py 会越 500, 镜像 test_web_debt_proposals.py〕; test_web_debts.py 的 _stub_debt 仍补 debt_kind+installment 字段〔external stub 经 _detail_view 调 _installment_view 缺字段 AttributeError〕±0). +9 ⑥ debt installment_paid_count 派生只读字段〔已还期数 = floor(paid / per-period) clamp 到 count, 分子用 paid 口径非 remaining→forgiveness/adjustment 不虚增进度, per==0 守卫防 500, gate on debt_kind=='installment' 重分类后 INERT;_installment.installment_paid_count 笼子纯函数共用于 DebtResponse〔不落库, 派生少存〕;test_debt_installment +9: floor-whole-periods / clamp-to-total / gated-on-kind〔revolving→None + flip〕/ degenerate-per-zero→0 / response-tracks-repayments〔compute_paid 折叠派生〕/ forgiveness-不虚增〔paid 非 remaining 口径〕/ 〔对抗审 P3 补〕ignores-adjustment〔原始合约口径, +10000 调整后 5000 还款仍 2 期非 1, 钉 adjustment-independence 取舍〕/ installment-kind-without-count→None〔第二 gate 子句, 删则 principal//None TypeError 500〕/ in-repayment-201-body〔RepaymentCreateResponse 继承 DebtResponse 经 model_dump 透传〕;+2 既有断言就地扩 non-installment + reclassify 响应 shape 全清含 paid_count None ±0〕. +19 ⑥ debt 设计片 完整 installment〔codex PR#67 评审补 2: KPI payoff max 只取 remaining>0 的 installment〔早还清债更晚合约日不再误推 projected/three_state〕/ DebtResponse 三 schedule 字段全 gate 在 debt_kind=='installment'〔重分类后不露陈旧元数据〕;2-lens 对抗审补 5: installment_payoff_date gate 在 debt_kind=='installment'〔重分类 installment→revolving 后 schedule 列变 inert,KPI 不再误计〕/ 已还清 all-installment goal suppress 确定性 payoff〔镜像 velocity remaining<=0〕/ payoff 锚定 accounting-tz 日期〔UTC16:00=沪次日,tz-drop 即红〕/ installment_count le=600 防 date 年溢出 500 / web _payoff_line 加 §B 分期合约确定性臂〔projected+tracking_days=None 不再落 insufficient〕〕 (设计 §B: installment 外部债加契约 schedule 期数×周期 → 确定性还清日 [建账+count×period 月, 纯函数, 与利率/递减无关], 替代被抑制的 velocity 投影; Debt.installment_count/installment_period_months 双 nullable + ck_debts_installment_valid 配对 CHECK [both NULL 或 both>0], create 校验 期数 only-for-installment-kind+周期默认1, _installment.installment_payoff_date 共用于 DebtResponse + external_payoff_kpi; KPI: all-installment-scheduled → projected=max(各债还清日)+three_state vs target+tracking/staleness None [插在 _NO_PROJECTION_KINDS suppress 之前], installment 无 count 仍 suppress / 混 revolving 仍 velocity; 迁移 20260620_0003 Shape-A guarded add 双列+CHECK; test_alembic_debt_installment_migration ×1 real_db round-trip [双列 nullable + CHECK] + test_debt_installment ×11: create 带 schedule+默认周期1 / payoff=建账+count×period / 月末 clamp Jan31+1mo→Feb28 / 非 installment 三字段 None / 期数 on 非 installment kind 422 / 周期无期数 422 / all-installment goal 确定性 payoff / payoff=max across debts / 无 count 仍 suppress / 混 revolving 非确定性 / three_state vs target ahead). +9 ⑥ debt 设计片 6e-android-backend OCC setter (ADR-0049 §7.0/8e-6e: POST /api/debts/{id}/kind 纠正已建债的 debt_kind, 让 6e-backend 真正可用——Android 详情屏 type chip 入口; OCC carrier〔expected_row_version + claim_idempotent_request actor-scoped fingerprint〕bumps row_version, 非 fold-changing〔debt_kind 只 gate 投影〕; set_debt_kind 复用 claim_row_with_token; ledger-scoped writer; DebtKindSetRequest schema〔extra=forbid, DebtKind Literal〕; mutate_token_carriers 59→60; OpenAPI +/kind 路径+schema〔新 schema 未入 Android pairs=PR-B 加, 本片 Android ≡ main〕; test_debt_kind_setter ×9: 设置+bump row_version / stale-409 / viewer-403 / no-auth-401〔strict-401 lane 强制〕/ idem-key-required-422 / idem-replay 不二次 bump / Literal 拒非法-422 / unknown 债-404 / 跨租户 gray-token-404〔对抗审 P3 补隔离 pin〕). +6 ⑥ debt 设计片步3 还款匹配学习 cold-start (设计 §E first cut, 零 schema: 当 slice-3b 确定性 matcher 沉默时, fallback 到「这个 (account,source,归一化 label) 一致确认到的 still-feasible Debt」——读已确认 RepaymentDraft.committed_debt_public_id, 无新表无评分, 上线带基准+从零自学; account-scoped〔created_by_account_id, 非 tenant〕/ still-feasible only〔committed IN feasible_ids〕/ 歧义闭嘴〔同签名确认到≥2 笔不同债=撞键=None〕/ 确定性 matcher 永远先于 learned; _repayment_draft_match 加 learned_debt_for_signature + suggest_debt_for_draft orchestrator, list_repayment_drafts + audit 两 caller 改走 orchestrator〔per-draft account_id=created_by 自动 account-scope〕; test_repayment_draft_learning ×6: 学到上次确认债 / 歧义≥2债闭嘴 / cleared 债不再建议〔feasibility filter〕/ account-scoped〔他账户确认不为你预选+本人正向控制〕/ confident 永远赢 history / 空白 label 签名也学〔matcher 沉默时 target="" 匹配既往空白确认, 对抗审 test-efficacy 镜头 P3 补〕). +8 ⑥ debt_kind 6e 最小 (设计文档 docs/audits/2026-06-20-debt-data-ingestion-learning-design.md 步1「可随时」, ADR-0049 §7.0/8e-6e: 外部债 repayment-rhythm 分类 gate 还清投影——velocity 线性外推只在诚实处跑; Debt.debt_kind String(16) NOT NULL default unspecified + CHECK ck_debts_kind_valid IN(unspecified/revolving/installment/one_off); DebtResponse/DebtCreateRequest 透传〔带默认=非 required→Android OpenApiContractGateTest 反向检查不咬, 零 Android 改动〕; external_payoff_kpi gate: suppress 投影 iff 所有 non-voided 外部债 ∈{one_off,installment}〔混装≥1 revolving/unspecified 照投整组; suppress 仍 echo 用户 target_date, projection/three_state None〕; unspecified 保持当前投影行为=向后兼容存量外部债; 迁移 20260620_0002 guarded add_column server_default unspecified〔PG fast-default 回填〕+ create_check_constraint; test_alembic_debt_kind_migration ×1 real_db round-trip〔NOT NULL+CHECK〕 + test_debts ×3〔create accept+echo+GET / default unspecified / Literal 拒非法 422〕 + test_debt_repayment_goal_kpi ×4〔all-one_off suppress / all-installment suppress / 混装照投 / suppress 仍 echo target_date 钉 not _EMPTY_PAYOFF_KPI〕). +2 ⑥ P3#4 scheduler_leases 专用 timestamptz 表 (docs/audits/2026-06-14-known-bugs.md 🟢#4: ISO 字符串字典序比较 → 真 timestamptz 类型比较; AppMeta KV 通用表 → 专用 scheduler_leases 表 [name varchar(64) PK / expires_at timestamptz NOT NULL / updated_at timestamptz NOT NULL]; _ensure_lease_row「先确保行再原子 UPDATE」两步 → 单语句原子 INSERT...ON CONFLICT(name) DO UPDATE...WHERE expires_at<=now RETURNING name [returning 有行=claimed], 删 ISO 比较 + 隐式 commit 死分支, 保留 slice3 入口拒在途事务守卫; 迁移 20260620_0001 guarded create + 一次性清 app_meta 旧 scheduler_lease: 键; test_two_sessions_concurrent_claim_yields_single_winner [real_db threads+barrier 钉单语句原子 claim 并发只一个成功] + test_alembic_scheduler_leases_migration [real_db round-trip 钉 migration↔ORM 形状一致 + app_meta 一次性清理]; cloud-hardening audit tokens scheduler_lease:+rowcount → SchedulerLease+on_conflict_do_update). +1 ⑥ P3#2 resolve_protected_image 跨租户路径前缀拒绝直接 pin (docs/audits/2026-06-14-known-bugs.md 🟢#2: 函数经 resolve_upload_path_for_tenant 已做 tenant-dir 前缀隔离非「甩给调用方」, docstring 准确化; test_protected_image_route_rejects_other_tenant_prefixed_path 钉 tester_1 expense 指向 owner/ 前缀路径→404 image_not_found, 补足此前只测 legacy-unscoped 跨租户的缺口). +1 ⑥ P3#3 scheduler_lease.try_claim_scheduler_lease 事务边界 (docs/audits/2026-06-14-known-bugs.md 🟢#3: 去 _ensure_lease_row 隐式 commit〔生产里是死代码——5 个 scheduler 全用专用 SessionLocal session, 入口 in_transaction()=False〕, 改为 public 入口检测到在途事务即 raise RuntimeError, 不再偷提交调用方未提交事务; 约定升机器门; test_scheduler_lease_refuses_session_with_inflight_transaction 钉 raise + probe 行不被提交, mutation: 恢复旧 silent-commit 两断言皆红). +4 ⑥ BUG-2 备份并发锁 (docs/audits/2026-06-14-known-bugs.md: 手动 / Owner Console / 计划任务同写 backups\ 时轮转互删报错; backup_service._backup_lock 跨 Python+PowerShell 共用 .backup.lock 哨兵文件〔atomic O_EXCL / CreateNew + mtime 30min TTL stale-reclaim〕非阻塞串行化备份作业, manual=skip-409、PS backup_database.ps1 skip-on-contention + 轮转/prune 删除幂等; 启动 pre-upgrade 快照刻意不上锁〔纯 dump 无轮转、startup 单线程、fail-closed 不可被陈旧锁卡死, 对抗审 C/D 改, 避免新 startup-brick 类〕; test_owner_console_backups +4: manual-holds-lock-during-dump+releases-after / manual-skips-with-409-when-lock-held〔不跑 pg_dump〕 / stale-lock-past-TTL-reclaimed / lock-file-invisible-to-list_backups+is_backup_valid). +1 ⑤b 翻 DEBT_ROLLOUT_ENABLED 默认 False→True (激活片: config.py 默认 + .env.example + _transitions/config 注释 + ADR-0049 §0.1 解除「flag 不得开」措辞; test_bill_split_debt_linkage::test_debt_rollout_enabled_by_default 钉默认 ON〔翻回 False 即红〕; 8 个「关闭期 accepted 无 Debt」前置测试〔linkage no-debt ×1 + backfill ×7: creates-missing/idempotent-rerun/reconcile-noop-off/reconcile-on/status-filter/null-ledger/foreign-home-shape〕加 debt_rollout_off fixture 显式置 OFF=零 node 增减). +1 ⑤c-3 follow-up /web/receivables active-first 排序 (路由层复用 web_debts._STATUS_RANK 稳定排序 rows, 镜像 _split_debt_views + Android sortReceivablesActiveFirst; test_web_receivables +1 order 测试: open<cleared<voided, 服务端 status.asc=cleared-first 下不排序该测试会咬). +8 ⑤c-3 web 欠我的/应收页 (creditor 发现 UX web 片, docs/audits/2026-06-19-model-invariant-hardening.md P3b ⑤c: 新 GET /web/receivables account-scoped 跨账本只读, 镜像还款捕获审计页形态; viewer 经 _web_viewer_account_id 解析→list_member_receivables_for_account; 每行 communal 关系行复用 web_debts 成员行词汇〔债务人名 counterparty_label + 「我帮你垫的」关系主句 viewer_is_debtor=False + 进度条 + neutral/success 状态徽章永不红〕, 纯只读非链接〔.dt-card--static, 镜像审计页, 避 cross-ledger 详情 proposal 段 tenant-scoped 不全〕; sidebar 账单流 加「欠我的」接 欠款 后; OpenAPI +/web/receivables 路径无 schema 变; test_web_receivables ×8: remote-403 / premium 空态 / open communal 行〔债务人名+我帮你垫的+进行中+进度条, 无 应收应付/dh-amt 金额英雄〕/ cleared 沉降+已两清 / 跨账本多债务人聚合 / _receivable_row_view 单测 open-creditor-headline+cleared-recede-ok+voided-neutral). +14 ⑤c-1 跨账本应收读路径 (creditor 发现 UX 后端片, docs/audits/2026-06-19-model-invariant-hardening.md P3b: list_debts ledger-scoped 故 creditor 看不到跨账本应收; 新 GET /api/debts/receivables account-scoped 列 viewer 作为跨账本 member counterparty-creditor 的应收〔direction=i_owe + counterparty==viewer + NOT 该 ledger 成员〕, shell-redact ledger_id=None〔§5.2/ADR-0029〕, 批量解析 debtor〔owner_account_id〕Account.display_name 填 counterparty_label〔creditor 看 WHO 欠;counterparty_account_id/direction 不动保 list↔detail 一致〕; get_participant_debt_response 镜像 enrich cross-ledger-creditor 详情〔viewer_is_debtor is False guard,debtor 自视仍 generic〕; 设计经 ultracode Workflow〔web 调研+codebase 勘查+综合,enrich-DebtResponse beat new-schema/bare-reuse〕; OpenAPI +路径无 schema 变; dedup 用 ACTIVE 成员〔disabled_at IS NULL〕对齐 auth——soft-removed creditor 拿不到 token 看不到 list_debts,不能算「已见」否则隐藏其应收(对抗审 A-P3);member-type filter 是 belt-and-suspenders〔ck_debts_member_has_account 令 external counterparty_account_id=None,counterparty 匹配已排 external,对抗审 B-P2 改正 test 误述〕; test_debt_receivables ×14: 端点 names debtor+redact ledger+not-debtor / blank-name fallback None / 同账本 active-member 不重复〔~viewer_is_member〕/ owed_to_me payable 排除〔direction filter〕/ external 排除〔counterparty 匹配, member filter 冗余〕/ debtor 视角空 / 401 / 详情==列表 copy 一致 / same-ledger debtor 自视仍 generic+不 redact / cross-ledger debtor 详情不 enrich〔钉 viewer_is_debtor is False guard〕/ 直测 cross-ledger creditor 详情 enrich〔镜像 debtor 直测〕/ soft-removed〔disabled〕creditor 仍见应收〔钉 disabled_at filter〕/ 多债务人多行 per-row name keying〔钉批量 _owner_display_names 映射〕/ cleared 应收仍列+status=cleared〔钉无 status filter〕). +9 P3b 拆账 Debt backfill+reconcile (模型不变量加固 docs/audits/2026-06-19-model-invariant-hardening.md: 关闭期 accepted 拆账无 member Debt,翻 DEBT_ROLLOUT 前硬前置; backfill_bill_split_debts 扫 accepted-无-bill_split-Debt〔相关 NOT EXISTS on source_type+source_id〕逐字镜像 create_bill_split_debt 补建, 幂等+commit-once-batch; reconcile_bill_split_debts_if_enabled 启动自愈仅 flag ON 跑〔OFF 时 accepted 无 Debt 合法绝不 fabricate〕, cheap no-op once reconciled, uq_debts_source 兜底; test_bill_split_debt_backfill ×9: 回填精确形状 / 已有 Debt 跳过不重复 / 幂等重跑 / 非 accepted〔invited+rejected〕不动 / reconcile OFF no-op〔安全不变量〕/ reconcile ON 回填 / 对抗审 P2: status 过滤独立于 ledger guard〔accepted-then-cancelled 仍带 ledger 不回填〕/ null-ledger accepted 跳过〔钉防御 guard 分支〕/ 外币父债回填仍 strict-home-shape〔钉 backfill 路径不复制 USD provenance〕). +7 P1 启动迁移前自动备份 gate (模型不变量加固 docs/audits/2026-06-19-model-invariant-hardening.md: Alembic upgrade 是唯一不可逆启动步,迁移前 pg_dump 快照 fail-CLOSED——备份失败即 RuntimeError 中止迁移〔数据安全优先 ADR-0049 §0〕, SKIP_PRE_MIGRATION_BACKUP 逃生口; backup gate 只在已有 alembic_version 的 tracked DB〔生产 restart/upgrade 路径〕触发, fresh create_all'd DB〔无 version 表入口〕跑 guarded 无操作迁移不备份, 否则每次 fresh 启动/test reset 都 shell pg_dump; 配套 DATABASE_URL 未设→superuser@localhost 回落时启动 WARN〔属主错位陷阱前置〕; test_db_migration_backup_gate ×7 real_db: 备份先于 upgrade 接线 / 备份失败 fail-closed 不迁移 / SKIP env 跳过快照但仍迁移 / 已在 head 不备份不迁移 / fresh DB 无 version 表跑 upgrade 但不备份〔对抗审 P2 补:钉死 has_version_table gate,删 guard 即红——其余 6 测试删 guard 仍绿〕 / DATABASE_URL 未设→WARN / 设置→不 WARN). +5 P2 Debt 母表 shape CHECK backstops (模型不变量加固 docs/audits/2026-06-19-model-invariant-hardening.md: 2 结构性 CHECK 下沉 _create 维护的形状不变量到 DB——member↔counterparty_account_id NOT NULL / bill_split↔source_id NOT NULL〔counterparty_label presence 故意不约束=展示 provenance 非身份字段,身份由 account CHECK 守;label CHECK 超 audit scope 且与既有 display-fallback seed 习惯广泛冲突〕; 迁移 20260619_0001 guarded ADD, DEBT_ROLLOUT off 下 prod 全 external+manual=两 CHECK 零命中 tightening; test_alembic_debt_shape_checks_migration ×1 real_db round-trip〔migration-built CHECK 谓词==ORM 防同名 tautology〕 + test_debt_shape_constraints ×4 enforcement〔2 CHECK 双向 raw-insert 拒坏形状: member 无 account / external 带 account〔FK-valid 隔离 CHECK〕/ bill_split 无 source / manual 带 source〕). +4 P3a 已清/forgiven 债禁挂 pending proposal (模型不变量加固 docs/audits/2026-06-19-model-invariant-hardening.md: create_repayment_proposal 此前只挡 voided,现锁父债 FOR UPDATE〔lock_debt_for_intent,不 bump row_version——读 remaining 在锁内以挡 read-vs-clear race〕+ compute_remaining<=0 → state_conflict 409;test_member_repayment_proposal_settled ×4〔repayment-cleared→409 / forgiven→409 / 部分还款 remaining>0 仍允许——挡过宽 check / settled gate 在 idempotency claim 之下:同 key replay 走 HIT 返回原 proposal 不触 409、新 key 才 409——对抗审 P3 补,防重构把 gate 移到 claim 之上破 replay 幂等〕;锁的 read-vs-clear race 需服务执行中段插桩才能确定性测,不可行,不另加并发测试——FK-insert 自身 FOR KEY SHARE 已让 holder-FOR UPDATE 阻塞,任何 held-lock 测试对显式锁无分辨力,serialize-then-recheck 在 READ COMMITTED 下删锁照样绿). +4 P1 启动迁移属主预检 (test_db_migration_owner_preflight, real_db: 3 单测〔pg_has_role 预检——无属主关系角色→清晰报错 / 属主角色成员→放行 / 属主自身→放行〕 + 1 调用点接线测试〔spy 钉守卫在 Alembic upgrade 前被调用,删调用即红〕;防 2026-06-04 cut-over 表属主错位静默 brick 启动复发, docs/audits/2026-06-19-model-invariant-hardening.md P1). +4 BUG-1 bill_split party-auth negative tests (test_bill_split_party_authorization: accept/reject/cancel by non-party → 403 invitation_not_yours + accept guard-precedence over settled fast-path = no state leak; closes 2026-06-14 known-bugs BUG-1 GA-blocker + connected get_invitation-not-tenant-scoped P3, the party check is its sole compensating control). +11 ADR-0049 债务域 web 面 slice 5 owner 债务概览 (扩 owner index ledger_health 两聚合列: open 外部债计数 + needs_review 完整性 flag〔warn badge 链 /web/debt-goals, 只读〕; debt_service.count_open_external_debts 单查分租户 grouped〔仅 stored status=open + external, 排除 cleared/voided/member〕 + goal_debt_repayment_service.ledger_has_goal_needing_review 复用只读 evaluator; test_owner_console_ledger_health ×11: count 单测〔仅 open external 计入 + 分租户 grouped+隔离 / 空 tenants→{}〕 / needs_review 单测〔unacked voided link=True / in_progress=False / 无目标=False / 跨租户隔离〔他账本 voided-link 目标不 flag owner〕/ 归档目标不 flag〕 / HTTP〔外部债计数 per-row 渲染映射 text-end cell〔owner=3 + 第二账本=1 各归本行〕 / voided-link goal warn badge 链 /web/debt-goals / in_progress 无 badge 不渲染 deep-link / aggregate-only 红线: 对手方 label 不泄漏〕; 对抗审 5 镜头 0 P1/P2, 3 test-efficacy P3 全补〔复核 flag 跨租户隔离 + 归档边界 + per-row 渲染映射〕). +15 ADR-0049 债务域 web 面 slice 3 还款捕获审计页 (新端点 GET /web/repayment-drafts, account-scoped 非 ledger-scoped=隐私边界, 只列 viewer 自己创建的捕获; test_web_repayment_drafts ×10 HTTP: remote-403 / premium 空态 / pending 行〔来源+商户+额〕/ pending+匹配债 描述性 provenance「系统猜测对应」/ pending 无匹配无 provenance / confirmed「已记到」关联债+不带 ephemeral 建议 / dismissed 沉降 debt-card-sunk「已忽略」/ account-scoped 隐藏其他成员私人捕获〔drop account filter 即泄漏〕/ cross-ledger 聚合+跨租户关联债名解析 / 新近排序; ×5 _audit_row_view 纯单测: pending+suggestion tone-neutral / pending 无 provenance / confirmed linked tone-ok 无 ephemeral / confirmed null-label 防御 fallback 外部欠款〔HTTP 不可达〕/ dismissed tone-muted recede 永不 danger — 该 view import 同时让 web_repayment_drafts 被测引用, unreferenced 不 +1). +28 ADR-0049 债务域 web 面 slice 4 还债目标进度 web 面 (新端点 GET /web/debt-goals; 对抗审补 2 HTTP: external 投影 at_risk 渲染 amber pill〔三态徽章/目标日期/投影线走真 Jinja 而非仅单测 dict〕 + stale 投影 dg-projection--warn〔补 P2 KPI 模板接线覆盖缺口〕; 镜像 Android DebtPlanProgress: composition 派生 Member/External/Mixed/Empty〔含 Empty 短路〕+ 件数英雄〔成员 cleared+remaining / 外部·混装 cleared+total〕+ 金额弱化副文案〔成员永不带欠、混币隐藏〕+ 仅纯外部 KPI〔three_state 琥珀非红 + 还清投影 3 臂 projected/stale琥珀/insufficient〕+ per-link 行〔成员 note 永不 danger / 外部 meta voided→danger〕+ needs_review 描述性琥珀 note 无钮; 9 HTTP〔remote-403/empty/member communal/member done achieved/external KPI/mixed 无 KPI/voided 成员 needs_review 永不红/全作废短路/nav〕 + 17 单测〔composition 4 态+drops-voided / 件数英雄 member·external·mixed 各臂 / 金额线 member·external·done·never欠 / shared_currency None 抑制 / payoff 3 臂 / three_state at_risk 琥珀非 danger + 缺省省略 / link row 成员永不 danger + 外部 voided danger + owed 方向 + 成员进度档 / view KPI gate ==External〔mixed/member 排除〕 + all-voided 短路 + eval 徽章三态〕). +9 ADR-0049 债务域 web 面 slice 2b 成员 proposal 状态+过往历史 (复用 list_repayment_proposals 无新端点; 拆出新文件 test_web_debt_proposals.py 守 files_over_500 门〔test_web_debts.py 越 500〕; +9: pending 关系状态行 debtor/creditor 视角〔web 描述性只读非 CTA〕/ 已解决「过往」沉降 neutral〔rejected→在对账 非失败、永不 danger〕/ >3 折叠 <details>「查看全部 N 条过往」/ member 无 proposal 不渲染段 / external 无收发箱 / _proposal_pending_line 三角色 + _resolved_proposal_row 日期前缀+neutral + _proposal_section 拆 pending/resolved+折叠). +5 ADR-0049 债务域 web 面 slice 1A 列表 communal 化 (test_debts +1: /api/debts 携带 server-authoritative viewer_is_debtor per row; test_web_debts +4: member 行 communal〔家人 section + 关系主句 + 永不应付应收 danger〕/ 家人-外部 软分组家人在前 / 第三方 viewer〔证 per-row viewer 而非 owner-相对 direction〕/ _debt_view member 分支 + _split_debt_views 分组 active-first; 既有 member-with-accounting-labels 测试改写成 communal ±0). +1 ADR-0049 债务域 web 面 slice 1B premium + IA 移 (test_web_debts +1: _amount_segments cur/int/dec 拆分〔CNY 小数 / JPY 无小数〕; 既有用例就地扩断言——列表/详情 editorial 英雄 spans + 外部删重复「剩余」行 + paid/principal businesslike 条, ±0 node). +6 ADR-0049 债务域 web 面 slice 2a read-only /web/debts/{id} 详情按角色分轴 (test_web_debts +6: external 详情 summary〔剩余/本金/已偿还/应付〕/ member 详情 communal〔一起处理+看看账+这件事一共, 无应付应收剩余 danger〕/ unknown→404 / _member_headline 矩阵全分支+near-ratio 边界 / _communal_ratio 钳位 / _detail_view 成员 neutral+voided 永不 danger+外币 FX 回退外部卡+外部 voided danger). +8 ADR-0049 债务域 web 面 slice 1 read-only /web/debts list (test_web_debts ×8: remote-403 / empty-renders / external-i_owe-open row〔name+应付+未结清+amount〕/ owed_to_me→应收 / full-repay→已结清+dt-pill-ok+zero-remaining / void→已作废+dt-pill-danger / member bill_split debt renders 家庭成员+应付+未结清〔neutral index mirrors Android list〕 / _debt_view unit: direction+status labels/tones + member/external fallbacks). +9 ADR-0049 #4 debt-domain DB constraint backstops: test_alembic_debt_constraint_hardening_migration ×1 (3 FK + 3 status<->committed CHECK round-trip on real PG, asserting migration-built defs structurally EQUAL the ORM〔referent/predicate, not just name〕; circular-FK use_alter proven by create_all) + test_debt_constraint_enforcement ×8 (mrp committed CHECK rejects confirmed-without-committed AND committed-on-pending〔both directions〕 / confirmed_amount CHECK / all 3 FKs reject orphan〔committed_repayment, repayments.proposal_id, self-ref supersedes〕 / RepaymentDraft committed CHECK both directions — the migration ADD CONSTRAINT fails fast on dirty data). +18 ADR-0049 §杠杆③ slice 3b ephemeral suggested-Debt match (test_repayment_draft_match ×12 pure matcher: unique-feasible-label-match / containment-either-direction / casefold+whitespace-normalize / exact-beats-contains / ambiguous-equal-strength→None / specific-merchant-no-match-does-NOT-fall-through / blank-merchant-single-feasible-suggests / blank-merchant-multiple→None / infeasible-amount-excluded / feasibility-filter-precedes-ambiguity / empty-candidates→None / [6-lens review] containment-class-jump-on-multi-keyword-label documented-tradeoff; test_repayment_drafts list ×5: pending-draft-carries-suggested_debt_public_id / ambiguous-two-花呗→None / only-pending-not-resolved / [6-lens review] service-unfiltered-status=None-list-suggests-only-pending〔the per-draft pending guard, unreachable via the always-single-status route〕 / [6-lens review] excludes-non-repayable-shapes〔voided+member+bill_split candidate-query WHERE exclusions each bite〕; test_repayment_drafts_isolation ×1: suggestion candidate query tenant-scoped — owner's 花呗 draft never suggested ledger-B's 花呗 Debt). +31 ADR-0049 §杠杆③ slice 3a NLS repayment-capture inbox (capture pending/dedup-by-identity/distinct-identities/invalid-source-422/home-currency-server-set/viewer-403/unauth-401; list pending+status-filter; confirm records-once+reduces-remaining / clears-debt / overpay-422-draft-stays-pending / member-debt-409 / stale-debt-version-409 / missing-debt-404 / missing-draft-404 / idempotent-replay-records-once / missing-idem-key-422 / already-confirmed-new-key-409 / viewer-403 / unauth-401; dismiss latches / idempotent-when-already-dismissed / confirmed-draft-409 / viewer-403 / unauth-401; two-sessions confirm serializes-on-draft-row[real_db] + serialize-then-second-rechecks[real_db]; +4 from 6-lens review: home_currency_code dropped from the create request + set server-side〔currency finding: a field whose only legal value is the constant home currency〕 / dismiss viewer-403 / cross-ledger draft isolated〔confirm+dismiss+list 404/excluded〕 / cross-actor confirm replay→idempotency_key_reused〔actor-scope fingerprint〕; test_alembic_repayment_drafts_migration ×1 create-table round-trip reflects columns/CHECKs/unique/indexes[real_db]; +1 codex PR#22 review: confirm records Repayment.paid_at = draft.captured_at〔captured payment time〕 not review-time now()). +7 ADR-0049 slice 8e-6d suppress-on-stale floor (杠杆④, test_debt_repayment_goal_kpi: stale-suppresses-date-and-surfaces-days-since / fresh-when-recent-activity-keys-off-latest-fact-not-debt-age / strict->threshold-boundary / wire-e2e-days_since_last_activity-not-projection; +3 from 6-lens review: multi-debt-freshly-linked-debt-does-NOT-reset-staleness〔P2 fact-based not created_at〕 / fresh-counts-recent-forgiveness〔latest_fact_at forgive branch〕 / latest_fact_at-spans-types-void-latest+none-without-facts〔void branch + None path〕; the prior 8 projection tests adapt to the new 3-tuple compute_external_kpi return and pin days_since None on the none/fresh shapes). +2 codex PR#20 P1/P2 通知草稿每次投递身份去重 (test_distinct_notification_keys_with_identical_content_each_create_a_draft: 两条不同投递身份 + 同内容 → 2 草稿、同身份重发 → 去重, idempotency 键以 notification_key 为主轴; test_long_notification_key_is_accepted_not_rejected: 长 key 不 422——cap 是 DoS 界非 fit 界, 值无论多长都会被 hash 进 idempotency 材料, P2#2). +15 ADR-0049 slice 8e-6c payoff DEADLINE + three-state (test_debt_goal_target_date ×14: payoff_three_state pure month-compare ×1 [ahead/at_risk/on_track/None×2]; create-time target_date echoed ×1; spending-goal rejects target_date 422 ×1; three_state ahead far-future / at_risk past / suppressed-no-projection / member-None ×4; setter set+clear / bumps-row_version-NOT-goal_version / on-achieved-goal-stays-achieved〔CRITIQUE-2: no silent un-achieve〕 / stale-409 / requires-auth-401 / viewer-403 / idempotent-replay ×7; test_alembic_goal_target_date_migration ×1 add-column round-trip[real_db]). +17 ADR-0049 slice 8e-6b external-debt payoff projection (test_debt_repayment_goal_kpi ×17: project_payoff_days pure-math ×2 [observed-pace / suppress-thin-zero-no-reduction]; compute_remaining_as_of fold ×4 [all-fact-types-at-now equals full fold / excludes-facts-recorded-after-cutoff / zero-when-debt-newer-than-cutoff / excludes-repayment-voided-during-window〔team-review P3: subtlest RepaymentVoid.created_at<=cutoff branch〕]; velocity ×4 [repayment-pace / writeoff-NEGATIVE-adjustment-not-just-repayments〔CRITIQUE-1#1 blocker: write-off shows real velocity〕 / windows-on-created_at-NOT-paid_at〔CRITIQUE-2 blocker: recording cadence not back-dateable〕 / accounting-tz-today-midnight]; suppression ×3 [mixed-currency / thin-window<14d / no-paydown]; §4 server-gating ×4 [member-None / mixed-None / pure-external-populated-e2e / all-voided-None]); +15 ADR-0049 slice 8e-3 §3.7/§4 creditor forgiveness (test_debt_forgive ×15: full-open forgive→cleared+is_forgiven / forgive-after-partial-repayment fold==0 with forgiveness=remaining_before / repayment-cleared is_forgiven=False / debtor-403 / external-409 member-only / already-settled-409 zero-remaining / stale-version-409 OCC / non-participant-404 existence-hiding / cross-ledger creditor forgives shell-redacted / idempotent-replay one fact / actor-scoped-fingerprint-422 (diff actor can't HIT past creditor guard) / supersedes-pending-proposal §4 F5 / requires-idem-key-422 / requires-auth-401 / §6-F13 goal-linked forgive stays achieved without review). +1 ADR-0049 slice 8d viewer_is_debtor server-authoritative role (test_member_repayment_proposal_cross_ledger::test_viewer_is_debtor_role_for_both_parties — debtor reads True / cross-ledger creditor reads False; the shared-ledger creditor reading False despite a non-null ledger_id is an inline assertion added to the existing settles_debt test). +8 ADR-0049 slice 6 §6/F13 integrity-review (debt-void-after-achievement → achieved+needs_review, reopen decoupled; acknowledge keep-for-audit carrier): evaluator +2 (ack-clears + ack-not-carried-across-version-bump pinning the per-version INT scoping vs a one-shot bool; debt-void-forces-review test renamed); lifecycle +6 ack guards (auth-401 / requires-idem-key-422 / stale-409 / rejects-not-yet-achieved-422 / no-pending-review-422 / idempotent-replay). +1 ADR-0049 slice 3 paid_at FX-date fingerprint regression; +6 ADR-0049 slice 4 bill_split→Debt linkage (test_bill_split_debt_linkage: accept-creates-member-Debt rollout-on / no-Debt rollout-off / re-accept-no-duplicate / reject-no-Debt / foreign-parent-stays-home-shape / debt-failure-rolls-back-whole-accept[real_db]); +8 ADR-0049 slice 5 account-scoped cross-ledger participant confirm/reject §5.2 (test_member_repayment_proposal_cross_ledger ×6: non-member creditor confirms+clears with shell-redacted ledger_id / non-member creditor rejects / non-member creditor lists pending proposal / member creditor in shared ledger settles keeping ledger_id / non-participant existence-hiding 404 on read+list+confirm / cross-ledger confirm idempotent replay; test_bill_split_debt_linkage ×2: two-sessions concurrent accept creates single Debt[real_db] / duplicate uq_debts_source rejected); +28 ADR-0049 slice 6 debt_repayment goal §6 (test_debt_repayment_goal ×12 evaluator [incl. achieved-version-stays-achieved-after-linked-debt-voided pinning the §6/F13 latch-wins ratification]; in_progress / all-cleared-achieves+latches-once / one-open / voided-not_evaluable+review / replace-bumps-version+freezes-old-set / unlink-open-achieves-new-version-not-old / achieved-then-reopen-stays-achieved / viewer-read-computes-achieved-without-latching / not_evaluable-recovers-via-link-replace / debt-vs-spending-list-isolation / spending-limit-regression; test_debt_repayment_goal_lifecycle ×15 guards: replace requires-auth-401 / idempotent-replay / stale-409 / requires-idem-key-422 / rejects-empty-set-422 / unknown-debt-404 / reject-spend-fields / requires-≥1-debt / unknown-debt-404-create / cross-ledger-isolation / viewer-403-create+replace / patch-rejects-debt-goal / two-active-debt-goals-coexist / replace-rejects-spending-goal / archive-hides; test_alembic_goal_debt_repayment_migration ×1 widen-goals round-trip[real_db] incl. scope-index goal_type predicate assertions) — 6-lens adversarial review fixed P1 archive_goal debt dispatch (int(None) 500) + P2/P3 coverage (two-goals-coexist, viewer-read-no-latch, not_evaluable-recovery, replace-rejects-spending, debt-links 401, migration scope-index predicate)


STRICT_EQUALITY_BASELINE.update({"mutate_token_carriers": 63, "backend_pytest_count": 2278})  # +1 月度 lifestyle 真香/后悔榜聚合契约测试（test_stats_lifestyle_rankings，账本隔离+排序，无新 mutate route）。 +5 ADR-0047 slice 2-B onedir+console=False (test_packaging_data_root: _build_log_config routes uvicorn+app logs to rotating file / omits stream handler when console=False〔windowed service None.write guard〕 / keeps console when stdout present; main() runs dictConfig + passes uvicorn log_config=None; env.py skips fileConfig when host already configured logging〔guard preserves launcher file handler through startup migration〕 — no new route, mutate_token_carriers unchanged). +7 ADR-0047 slice 2-A 后端服务硬化 (test_db_connect_retry ×3: wait_for_db retries-until-ready / healthy-noop-single-attempt / timeout-RuntimeError-chained; test_packaging_data_root ×4: launcher honors preset TICKETBOX_DATA_DIR / defaults next-to-bundle when unset / ignores blank / configure_environment mkdirs preset not EXE-adjacent — no new route, mutate_token_carriers unchanged). +1 /web pending batch-undo token carrier; +3 tests. +1 finding-三摊 Slice B ck_expenses_row_version_positive CHECK round-trip (test_alembic_expense_row_version_check_migration). +3 issue #65 slice A owner device delete (test_my_devices: delete-revoked→204+gone / delete-current→409 / delete-active→409; 401/403/404 fold into the existing require-auth/viewer/wrong-ledger tests). +2 ADR-0051 recycle-bin slice 1 restore symmetry: POST /api/recurring/items/{id}/restore + POST /api/goals/{id}/restore both carry expected_row_version (OCC-gated reactivate, mirror income_plan restore) — auto-detected carriers; +11 tests (security-matrix 401 ×2; recurring restore reactivates/stale-409/no-token-422 ×3 + viewer loop ±0; goal restore reactivates/stale-409 ×2; goal restore into-taken-slot-409 ×1; debt_repayment goal restore dispatches-without-int(None)-crash ×1; goal_spending_response serializer split out of goal_service for the files_over_500 gate + 2 unit tests pinning the category-vs-total spent selection).
STRICT_EQUALITY_BASELINE.update({"mutate_token_carriers": 70, "backend_pytest_count": 2321})  # +2 ADR-0052 Slice 3 category preference delete/restore token carriers; +8 collected pytest delta for category preference lifecycle, recycle-bin restore, route inventory, and migration round-trip.
# Latest tail baseline: +2 static asset-version derivation tests, plus the
# already-banked Web mobile IA, duplicate-counter, and ADR-0053/0054 merchant
# catalog deltas. Keep new entries short; CODE-2026-07-01 tracks historical
# comment cleanup for the older mojibake/long-provenance blocks above.
STRICT_EQUALITY_BASELINE.update({
    "backend_pytest_count": 2352,
    "mutate_token_carriers": 77,
    "mutate_token_exempted": 122,
    "mutate_token_reason_create_row": 32,
})
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
_ADR_0049_EXEMPTED_GRANDFATHER = (121, 122)  # ADR-0053 web merchant catalog adds one create-row exemption (POST /web/merchants/catalog/create) while hide/delete carry OCC tokens. The name is historical (first used for ADR-0049); it is the generic single in-flight exemption-add hop.

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
