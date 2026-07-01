# Android IA / UIUX Phase 0 Audit - 2026-07-01

This is the product-design lead audit for the Android IA/UIUX refactor. It
freezes the page responsibilities, state-authority rules, and implementation
slices before more visual work lands. It should be read with
`docs/current/ANDROID_UIUX_IA_REFERENCE_2026-07-01.md`, which contains the
external product reference pass.

## Evidence Read

- Project rules: `AGENTS.md`, `docs/rules/ENGINEERING_RULES.md`, architecture,
  API, security, references, and relevant ADRs.
- Shared Android shell: `AppPageScaffold`, `AppScrollableContent`,
  `AppPageScrollableColumn`, `AppPageHeader`, `AppDataAuthorityStrip`,
  `AppStatusBanner`, `SettingsPageFrame`, design tokens.
- Root pages: `TodayScreen`, `PendingScreen`, `LedgerScreen`,
  `LedgerScreenContent`, `StatsScreen`, `SettingsRootScreen`.
- Insights components: `StatsLeadInsight`, `StatsOverviewTrend`,
  `StatsSpendTrendChart`, `ReportsInsightCards`, `ReportsInsightCharts`.
- Settings secondaries: connection, ledger switcher, family members, devices,
  join family, category rules, merchant aliases, tags, recycle bin, export,
  notifications, security, sync status, background tasks, appearance,
  background gallery/crop/preview, dashboard cards, about.
- ViewModel/repository evidence: stats source, pending cached snapshot,
  read-only gating, outbox/offline dispatchers, local fallback, and repository
  comments that keep backend authority explicit.

## Product IA Contract

| Page | Product job | Must answer first | Primary interaction |
| --- | --- | --- | --- |
| Today | Daily cockpit | Is the ledger current, and what is the next useful action? | Upload, manual entry, open pending/ledger/insights. |
| Pending | Review inbox | What needs review, what can be batched, and what is blocked? | Filter, batch confirm, edit missing fields, resolve duplicates, reject/undo. |
| Ledger | Confirmed record surface | What actually happened, and how do I find/edit/export it fast? | Search, filter, grouped scan, drill/edit, batch action. |
| Insights | Answer page | What changed, why, and where should I inspect? | Read conclusion, compare, rank, drill into ledger. |
| Settings | Governance center | Which account/ledger/device/source am I operating under? | Manage connection, family, rules, sync, safety, data tools. |

The five root pages should share one shell language, but not one visual shape.
Shared language means header rhythm, status/source strip, state feedback, bottom
safety, spacing, and typography tokens. It does not mean every section becomes a
large rounded card.

## Current Findings Matrix

| Surface | Current state | IA / layout issue | Data-authority issue | Required direction |
| --- | --- | --- | --- | --- |
| Today | Uses shared page header, data authority strip, open signal sections, and real pending/monthly state. | It is closest to the desired cockpit, but still needs tighter first-viewport priority and clearer "next action" hierarchy when both pending and month stats exist. | Counts appear to flow from state, not hardcoded values. Need preserve no fake duplicate/ready counts. | Keep open-section style. Make the first screen read as status + next action + work queue, not a decorative summary. |
| Pending | Uses shared shell, source strip, filters, bulk confirm, swipe actions, empty/loading/error states, and real queue counts. | Queue segmentation is present, but density can still feel card-heavy because each receipt row dominates the list. Batch mode needs stronger scan hierarchy. | `showingCachedSnapshot`, read-only, and action-in-progress states exist. Must keep local cache labeled and never show cached queue as backend fact. | Strengthen queue dashboard, compact rows, and close confirm/reject/missing/duplicate feedback loops. |
| Ledger | Has filters/tools/manual entry and source strip. Current worktree adds day grouping and collapsible long-day sections. | Existing ledger still risks becoming a filter lab before a readable history. Long lists require day-level folding and compact scan rhythm. | `syncedInCurrentSession` is used for backend tone; otherwise local cache. Need avoid implying stale cache is authoritative. | Make ledger a dense record surface: summary line, filters as context/tools, day groups, compact rows, export/search in tools. |
| Insights | Now has lead insight, server report use, sparse/dominant chart degradation, rankings, and comparison rows. | Still reads as a dashboard-card scheduler: dashboard keys decide layout, charts can still feel bolted on, and trend/category/report content is not yet a single answer flow. | Empty/current-month and future-month leaks were addressed, but every chart needs explicit source and no fake zero when server stats/report are missing. | Rebuild as an answer page: lead conclusion, month comparison, 7-day/recent signal only when meaningful, top contributors, anomalies, drill paths. |
| Settings root | Uses `SettingsPageFrame`, source strip, account summary, grouped entry rows, and resource-backed copy. | Entry count is high. Root page is better but still reads like a directory rather than a governance dashboard. | `serverSettingsFresh` controls backend/cache tone. Need include sync/outbox/account/role/device status as first-class governance signals. | Reframe root around account, ledger/family, data rules, connection/sync/safety. Keep entry rows dense and reduce card stacking. |
| Settings secondaries | Many pages use `SettingsPageFrame`, `AppStatusBanner`, `SettingsOpenPanel`, read-only gates, and empty states. | Coverage is uneven. Some pages are polished, others remain form-heavy or list-heavy without consistent header, source/status, empty, error, read-only rhythm. | Several pages have direct-only online operations or partial offline support. Each page must label what is cached, queued, direct-only, or blocked. | Audit and polish page by page; do not leave Settings root as the only refined surface. |

## Unified Skeleton Contract

All Android root pages and Settings secondaries should use these roles:

- Header: product title and short product subtitle only. No engineering wording.
- Source/status: one strip or inline state near the top when not fresh backend.
- Primary content: page-specific answer/work surface before secondary controls.
- Tools: filters, presets, exports, display modes, and planning controls live in
  compact rows, menus, or sheets unless they are the page's main job.
- Sections: prefer open sections, dividers, row groups, and concise summaries.
  Use cards only for repeated bounded objects, sheets, dialogs, or objects that
  genuinely need a frame.
- Empty/loading/error/offline/read-only: same visual grammar and copy level
  across pages. Empty means no data; loading means refreshing; cache means local
  snapshot; read-only means role/device cannot write.
- Bottom safety: no primary action, empty action, form submit, or list tail can
  sit under the floating bottom navigation or IME.
- Copy: all user-visible copy stays in resources. No hardcoded Chinese/English
  in Kotlin UI files.

## Data Authority Contract

- Backend remains the only authority for confirmed ledger facts, statistics,
  duplicates, roles, members, devices, and server settings.
- Android local data can support offline viewing, local pending creation, and
  optimistic display only when the state is labeled as cached, queued, failed,
  or waiting for sync.
- Android must not recompute server-authoritative statistics and present them as
  truth. Local estimates are allowed only as degraded display and must be named
  as such.
- Missing server data must not become fake zero, fake "updated", fake duplicate
  counts, or fake ready counts.
- Outbox states are user-facing workflow states: queued, syncing, conflict,
  failed, retry, drop/confirm. They are not hidden implementation details.

## Insights Information Contract

Insights should answer five questions in order:

1. How much is confirmed for the selected month?
2. Is that higher/lower than the comparison period, and by how much?
3. What changed recently, and is there enough variation to chart it?
4. Which category/merchant/tag contributes most?
5. What needs action: anomalies, budget risk, pending backlog, recurring signal,
   or data missing?

Chart rules:

- Use a chart only when it adds comparison, variation, concentration, or a
  drillable question.
- Sparse data should degrade to rows, facts, and ranking, not fake trends.
- A dominant peak should be explained as concentration, not hidden inside a
  flattened chart.
- The 7-day signal should not draw seven equal bars when the real story is "one
  active day" or "no meaningful variation".
- Month spend trend should not be both a bar chart and a line chart for the same
  question. Pick the clearest expression per question.
- A chart dependency is not required for the current static shapes. Revisit a
  dependency only for real interaction needs: selection tooltip, zoom/pan,
  stacked/grouped series, accessibility semantics, or animation that improves
  reading.

Merchant rules:

- "High-frequency merchants" means ranked by confirmed expense count. Amount is
  supporting context only.
- "Top merchants" or "merchant ranking by spend" means ranked by amount, with
  count as supporting context.
- The UI must not label an amount-ranked merchant list as high-frequency.
- If both views exist, the label, sorting metric, and supporting text must make
  the difference obvious.
- Backend already exposes count-ranked lifestyle `frequent_merchants` and
  amount/count selectable reports `merchant_ranking`; Android should request and
  render the correct one instead of reinterpreting the list locally.

## Page Slice Plan

1. Audit / Gap Register
   - Add this audit and register the remaining page-level gaps.
   - No behavior change.

2. Shared Shell / Components
   - Tighten shared header/status/empty/error/offline/read-only language.
   - Extract any root-screen god-object logic that blocks page work.

3. Today
   - Rework first viewport into current source, next action, work queue, and
     month signal.
   - Keep all counts from pending/monthly state and backend/cache labels.

4. Pending
   - Improve queue segmentation, compact rows, batch affordance, empty/cache
     state, and action feedback.
   - Preserve no fake repeated/duplicate counts.

5. Ledger
   - Finish current long-list slice: day grouping, folding, compact mode, and
     bottom-safe empty state.
   - Verify with real data and keep filters/tooling secondary.

6. Insights
   - Rebuild page flow around answer-first analysis.
   - Replace weak charts with fact strips, rankings, comparisons, and only the
     charts that communicate a clear point.
   - Add drill targets to ledger where contracts already exist; register missing
     backend query contracts instead of faking them.

7. Settings Root
   - Make Settings a governance dashboard: account, ledger/family, device,
     connection/sync, data rules, safety.
   - Reduce directory feel and card stacking.

8. Settings Secondary Pages
   - Refine each secondary page with the shared page frame, status feedback,
     empty/error/read-only/cached states, and bottom-safe forms.
   - Start with connection, sync status, devices, members, rules, merchants,
     tags, recycle bin, export, security.

9. Debt / Tests
   - Collect same-page visual/code debt found during each slice.
   - Cross-domain debts go to registers, not into unrelated commits.
   - Add focused ViewModel/component tests where state authority or UI decisions
     are risky.

10. True-Device Review
    - Start backend, bind official `com.ticketbox` package through device code,
      install a release/formal package, and inspect scrolling, clipping,
      keyboard, bottom nav, and dark/light/skin behavior on a real device.
    - If ADB/device/backend is unavailable, mark it unverified explicitly.

## Commit Slice Rules

Commits should stay reviewable and reversible:

- `docs: record android phase0 ia uiux audit`
- `android: tighten shared shell language`
- `android: refine today cockpit`
- `android: refine pending review queue`
- `android: refine ledger history flow`
- `android: rebuild insights answer flow`
- `android: refine settings root governance`
- `android: refine settings secondary pages`
- `android: cover uiux authority states`
- `docs: record android true-device review`

Each commit message/body should state what changed, why, authority/offline
impact, dependency impact, tests run, unverified items, and registered gaps.

## Open Gaps After Phase 0

- Insights drill-down contracts are incomplete for "chart point -> filtered
  ledger rows" and saved report presets.
- Insights needs a clearer merchant-ranking split: high-frequency merchants by
  count, spend-ranked merchants by amount, and optional category-filtered
  ranking only when the query contract is visible to the user.
- Settings secondaries still need page-by-page visual QA and state-authority
  review.
- True-device verification has not been completed in this session yet.
- Detekt Gray Debug still prints compiler-analysis warnings even when Kotlin
  compilation succeeds; keep it in code-debt follow-up.
- Current ledger long-list implementation is in the worktree and still needs
  focused verification before commit.
