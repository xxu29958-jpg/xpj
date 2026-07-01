# Android UIUX Audit Register - 2026-07-01

This register turns the Android IA/UIUX Phase 0 audit into an execution ledger.
It tracks each product-design issue by page, authority risk, verification need,
and commit slice. The Phase 0 audit defines the direction; this file is the
working control board for closing it without losing gaps between slices.

Read with:

- `docs/current/ANDROID_IA_UIUX_PHASE0_AUDIT_2026-07-01.md`
- `docs/current/ANDROID_UIUX_IA_REFERENCE_2026-07-01.md`
- `docs/current/UIUX_GAP_REGISTER.md`
- `docs/current/CODE_DEBT_REGISTER.md`
- ADR-0023, ADR-0024, ADR-0042, ADR-0044, and ADR-0055

## 2026-07-01 Scope Lock

The current goal is a product-design-led Android IA/UIUX refactor, not a
surface polish pass. This register is the acceptance ledger for the five root
pages, Settings secondaries, chart/insight data expression, and authority-state
language.

Do not mark a page done because one visible defect is fixed. A page closes only
when its product job, data source, offline/cache behavior, layout density,
resource-backed copy, interaction feedback, and device evidence are all recorded
below. If a feature contract is missing, register it here or in
`UIUX_GAP_REGISTER.md`; do not fill the gap with hardcoded Android data.

## Status Legend

| Status | Meaning |
| --- | --- |
| Registered | The issue is accepted and not yet implemented. |
| In progress | A slice is active or partially landed, but verification is not complete. |
| Fixed | The issue has a local commit or documented resolution. |
| Needs QA | Code or copy has landed, but true-device or screenshot review is still required. |
| Deferred | The issue needs a backend/API contract, dependency decision, or separate ADR before implementation. |

## Audit Gates

Every UIUX slice should close these gates before being called done:

| Gate | Required evidence |
| --- | --- |
| Product job | The page answers its assigned job before controls and decoration. |
| Backend authority | Confirmed facts, stats, duplicates, roles, members, devices, and settings remain server-authoritative. |
| Offline clarity | Cached, queued, failed, conflict, read-only, and direct-only states are named as user states. |
| Visual system | The page uses shared Android tokens and shell components without heavy card stacking. |
| Copy | User-visible Android copy comes from resources and avoids engineering wording. |
| Interaction | Primary actions, back behavior, sheets, keyboard, bottom nav, and error recovery have a closed loop. |
| Number layout | Amounts, counts, dates, and labels fit on narrow phones without ellipsis hiding the main fact. |
| Data expression | Charts, rankings, and summaries show a readable comparison or degrade to facts when data is sparse. |
| Verification | Relevant unit/Compose/ViewModel tests, detekt/lint/build, and true-device or emulator evidence are recorded. |

## Page Register

| ID | Surface | Status | Priority | Finding | Acceptance |
| --- | --- | --- | --- | --- | --- |
| AIA-001 | Global shell | Needs QA | P0 | The five root pages have a shared shell, but the final true-device pass must verify header rhythm, status language, bottom padding, and dense pages together. | Today, Pending, Ledger, Insights, and Settings share one skeleton language without becoming the same card layout. |
| AIA-002 | Data authority | Needs QA | P0 | Backend authority and local cache labels exist, but every page must keep cached/offline state below server facts. | Fresh backend, local cache, read-only, queued, conflict, and failed states are visibly distinct and never imply fake server truth. |
| AIA-003 | Today | Needs QA | P0 | Today now gives the month amount full width, includes the source/status in the month line, and derives a single next action from real pending state; true-device review still needs to judge density and amount fitting with live data. | The first screen states source, pending workload, month status, and next action without truncating large amounts. |
| AIA-004 | Pending | Needs QA | P0 | Pending now has a real queue overview derived from `state.items`; the 2026-07-01 density slice reduced repeated top metrics, compressed the queue overview, and made compact cards scan-first. User follow-up: when real unconfirmed bills exist, the item surface can still feel as card-heavy as the old Ledger page. Broader action/empty/offline QA remains open. | No fake duplicate/ready counts; the user can immediately see ready, missing amount, missing merchant, duplicate, and blocked work; item rows stay scan-first when the queue has real records. |
| AIA-005 | Ledger | Needs QA | P0 | The 2026-07-01 ledger density slice compressed the header, moved "记一笔" into the summary row, removed duplicate full dates from default rows, and tightened list typography. Multi-day long-history sampling still needs a larger backend dataset. | Confirmed records scan by day/month with compact rows, useful filters, no bottom-nav obstruction, and no large-card pile. |
| AIA-006 | Insights root | Needs QA | P0 | Insights has been reshaped, and the 2026-07-01 true-device pass fixed two authority-language defects: Budget no longer shows generic "month insight" content when no budget exists, and Goals no longer labels zero goals as stable. User follow-up: Budget/Tag drill pages may still show mismatched month-insight modules or unclear budget remaining/options copy. Full-page answer-flow review remains open. | The page answers spend, comparison, recent signal, top contributors, and action signals in that order; every tab and drill page uses the same answer model and does not reuse an unrelated module. |
| AIA-007 | Insights charts | Needs QA | P0 | Recent 7-day and month trend views must show comparison, variation, concentration, or degrade to facts. | No chart exists only as decoration; dominant or sparse data becomes facts/ranking, not flat bars or fake lines. |
| AIA-008 | Insights merchants | Needs QA | P0 | High-frequency merchants and spend-ranked merchants must stay separate. | Frequency lists sort by confirmed count; spend lists sort by amount; each row shows the active metric clearly. |
| AIA-009 | Settings root | Needs QA | P1 | The 2026-07-01 Settings root density slice tightened navigation rows and section titles, and initial server-settings fetch now presents a refreshing cache state instead of immediately labeling the page offline. Secondary inventory remains open. | Account, ledger/family, device, connection/sync, data rules, safety, and appearance are grouped by responsibility. |
| AIA-010 | Settings secondaries | In progress | P1 | Secondary pages are uneven. Sync status has improved, but other pages still need page-by-page state parity. User follow-up: the second-level surface language does not yet match the five root tabs, and several pages still read like isolated rounded cards. | Each secondary page has consistent title, back, explanation, loading, empty, error, cached/offline, read-only, success, destructive states, density, and component language. |
| AIA-011 | Copy and resources | Registered | P0 | New Android UI copy must not be hardcoded, and product copy must avoid engineering phrasing. | Touched user-visible strings live in `res/values/*.xml`; grep review finds no new hardcoded Chinese/English UI copy. |
| AIA-012 | Interaction closure | Registered | P0 | Confirm/reject/edit/undo/retry/read-only paths need consistent feedback across Today, Pending, Ledger, and Settings. | Every write action shows success/failure/queued/conflict and gives retry or recovery where applicable. |
| AIA-013 | Chart dependencies | Fixed | P1 | Android Vico was previously allowed but later retired for the current chart need. Future dependency work must not be aesthetic-only. | Native Canvas/token charts remain current; new chart dependency requires ADR-0023 review, official metadata, size/accessibility impact, and fallback. |
| AIA-014 | True-device review | Registered | P0 | The official package must be checked on a real phone after the audit-led slices, not only by code review. | Backend is started, official `com.ticketbox` is bound by pairing code, and screenshots/notes cover scroll, clipping, keyboard, nav, dark/light, and current real data. |
| AIA-015 | Visual density | Registered | P0 | Some screens can still feel crowded because summary, tools, filters, and records compete in the same viewport. | Each root page has one first-read story, compact secondary controls, and no nested pile of large rounded cards. |
| AIA-016 | Product copy tone | Registered | P0 | Offline/cache/error language must sound like product state, not casual chat or engineering status. | Copy uses calm states such as updated, offline data, waiting to sync, unavailable, read-only, and retry; no release copy says "backend", "local db", or casual phrases. |
| AIA-017 | Amount and metric fitting | Registered | P0 | Large monthly amounts and merchant/category metrics must never hide the primary number behind ellipsis. | True-device screenshots show full major amounts and count/amount labels across Today, Ledger, Insights, and Settings summaries. |
| AIA-018 | Ledger long-list efficiency | Needs QA | P0 | Default rows are now compact and day headers own date/subtotal context instead of repeating dates per record. The remaining risk is long multi-day data where group collapse thresholds and scroll depth need real-device review. | Ledger supports compact scan, day/month grouping, collapse where useful, and bottom-safe record tails. |
| AIA-019 | Insight drill contracts | Deferred | P1 | Mature insight reading needs "why" and "show me the bills" paths, but Android cannot invent ledger query truth. | Drill targets are added only when backed by backend-authoritative query/filter contracts and tested request parameters. |
| AIA-020 | Settings secondary inventory | Registered | P1 | Root Settings and Sync Status are not enough; every secondary page must be inspected and closed individually. | Connection, devices, members, join family, rules, merchants, tags, recycle bin, export, security, background, appearance, and about each have a recorded state pass. |
| AIA-021 | All drill / secondary pages | Registered | P0 | User observation: second-level pages, including Insight Tag/Budget/Goal drill pages and Settings secondaries, feel semantically inconsistent with root pages and too card-heavy. | Secondary pages inherit the same page frame, row density, section rhythm, state language, and bottom-safe behavior as the root tabs while keeping their page-specific job clear. |
| AIA-022 | Type and capsule alignment | Registered | P0 | User observation: capsule containers and text baselines can look visually off, with labels appearing crooked or poorly centered. | Buttons, pills, segmented controls, and status chips use shared token heights, padding, typography, and baseline alignment; true-device screenshots confirm text appears centered and not cramped. |
| AIA-023 | About / product trust page | Needs QA | P1 | User observation calls out "About Ticketbox" as part of the secondary-page mismatch. The current slice rewrites About as a compact trust page with version, confirmation boundary, sync authority, and screenshot/OCR boundary rows. True-device evidence is still pending. | About reads as a polished product trust page, not a diagnostics dump; version/build/support/legal rows are resource-backed, compact, and consistent with Settings secondaries. |
| AIA-024 | Edit / confirm detail | Needs QA | P0 | User screenshot `Screenshot_2026-07-01-23-48-19-093_com.ticketbox.jpg` showed the amount/currency edit surface with the keyboard open: the bottom action area became a large rounded block, actions formed a heavy 2x2 grid, and the amount section still used old card language. The current slice fixes the IME-state propagation root cause for floating bars, collapses keyboard-visible actions into a compact strip, and removes the heavy amount card in favor of a lighter form section with visible currency chips. | The edit/confirm detail page uses the same secondary-workbench language as Pending and Ledger, keeps keyboard actions thin and thumb-reachable, avoids hardcoded placeholders, and does not hide the form behind a large action card. |

## Secondary Settings Register

| ID | Page | Status | Required closeout |
| --- | --- | --- | --- |
| SET-001 | Connection | Registered | Fresh/backend failure/cache states, reconnect path, no exposed token/server internals in ordinary copy. |
| SET-002 | Sync status | Fixed | Queued, conflict, and failed offline mutations are summarized from real outbox state. |
| SET-003 | Devices | Needs QA | Device rows now use compact scan-first rows, overflow actions, resource-backed loading text, and device-specific missing-activity copy instead of the generic "未填写时间"; final true-device screenshot after the overflow-action update is still required. |
| SET-004 | Members | Needs QA | Member rows now keep role/status visible and move role/transfer/disable actions into an overflow menu; loading and audit loading states use product copy. Final true-device screenshot is still required. |
| SET-005 | Join family | Registered | Pairing/invite flow has clear loading, failure, expired, success, and back behavior. |
| SET-006 | Category rules | Registered | Rule list and edit states handle empty, conflict, queued, failed, read-only, and stale data. |
| SET-007 | Merchant management | Registered | Alias/catalog actions show conflicts and do not rewrite historical facts silently. |
| SET-008 | Tags | Registered | Rename/merge/conflict states follow backend contract and resource-backed copy. |
| SET-009 | Recycle bin | Registered | Restore/delete states make destructive behavior and backend authority clear. |
| SET-010 | Export/data tools | Registered | Export scope, failure, empty, progress, and local file states are explicit. |
| SET-011 | Security | Registered | Local biometric/token language stays separate from server authorization. |
| SET-012 | Background tasks | Registered | Worker status is local capability only and does not imply server processing. |
| SET-013 | Appearance/background | Registered | Preview/crop/apply flows are bottom-safe, reversible, and not visually isolated from the product system. |
| SET-014 | About | Needs QA | About now uses a compact product trust layout with resource-backed version, confirmation, sync, and screenshot/OCR boundary rows. Final true-device screenshot is required. |

## Functional Gap Register

| ID | Surface | Status | Gap | Required handling |
| --- | --- | --- | --- | --- |
| FUNC-INS-001 | Insights high-frequency merchants | Registered | The high-frequency merchant section must be count-ranked; amount-ranked rows cannot wear a frequency label. | Use backend count-ranked data or request `ranking_metric=count`; show spend only as supporting context. |
| FUNC-INS-002 | Insights spend ranking | Registered | Spend-ranked merchants/categories are useful but answer a different question from frequency. | Label as spend ranking and sort by amount; show count as secondary detail. |
| FUNC-INS-003 | Insight chart drill-through | Deferred | Charts do not yet close the loop from visible point/bar to filtered ledger records. | Register backend query contract first, then add UI drill and tests. |
| FUNC-INS-004 | Saved report presets | Deferred | Repeated analytical views are not first-class saved presets yet. | Add only after report query/filter contracts are explicit and server-authoritative. |
| FUNC-INS-005 | Insights budget state | Fixed | The Budget tab reused a generic "month insight" block, so an unconfigured budget could look like an active analytical module. | Budget now branches on real `BudgetProgress`: configured budgets show progress; missing budgets show a resource-backed "not enabled" state and budget setup entry. |
| FUNC-INS-006 | Insights goals state | Fixed | The Goals tab treated "0 enabled goals" as stable because status copy only checked for attention items. | Goals status now distinguishes Empty, Attention, and Stable; "stable" requires at least one real goal. |
| FUNC-INS-007 | Insights budget drill semantics | Registered | User observation: the Budget/Tag area can still show a mismatched "month insight" module and unclear remaining/options language even after the empty-budget root fix. | Audit the actual Budget/Tag drill path with backend data; split missing budget, no remaining amount, over budget, and setup option states with product-level resource copy. |
| FUNC-INS-008 | Insights goal taxonomy | Registered | User observation: "goal enabled" is not semantically clear enough. Goals should distinguish repayment, saving, and spending-control goals instead of relying on a generic enabled/disabled idea. | Goal rows and setup entries expose the goal type first, use backend-backed goal contracts, and avoid implying a goal exists when only a generic switch or empty state is present. |
| FUNC-LED-001 | Ledger long history | Needs QA | Long ledgers can become repetitive vertical scrolling. | Header and default row density are fixed in the ledger density slice; next validation needs many-day real data to tune day folding without hiding confirmed facts. |
| FUNC-SET-001 | Settings secondary state parity | Registered | Secondary pages do not all expose the same loading, empty, error, read-only, cached, and destructive states. | Close one page at a time and update the Secondary Settings Register. |
| FUNC-AUTH-001 | Offline creation and cache language | Registered | Android can create/cache offline, but must not present cache as authority. | Treat queued, syncing, failed, conflict, cached, and read-only as visible product states. |
| FUNC-PEND-001 | Pending compact scan density | Fixed | Compact mode still expanded duplicate-warning blocks and inline action buttons, so the first receipt could not be read in the first viewport. | Compact mode is now scan-first: duplicate state remains as a pill and action path, while large duplicate copy and inline buttons are reserved for Comfortable mode. |
| FUNC-PEND-002 | Pending real-item anti-card pass | Registered | User observation: with actual unconfirmed bills, Pending can still look like a stack of large cards, similar to the old Ledger problem. | Review real pending rows and convert the default queue into dense, readable rows with clear status/action affordances; reserve expanded containers for focused review or Comfortable mode. |
| FUNC-EDIT-001 | Edit keyboard action density | Needs QA | The receipt edit page is a shared path for Pending review, Ledger edits, and manual confirmation. With the keyboard open, a large action block can consume too much of the first viewport; the first implementation also needed the page skeleton to pass IME visibility before inset consumption. | Keyboard-visible actions now collapse into a compact action strip using skeleton-level IME state; primary and destructive actions remain clear; validation/status copy stays visible without becoming a large card. |

## Slice Register

| Slice | Status | Commit or target | Scope |
| --- | --- | --- | --- |
| S0 Audit and reference | Fixed | `a66393e3`, `0a829305`, current docs register slice | Phase 0 audit, product references, initial gap register, expanded acceptance ledger. |
| S1 Shared shell / authority language | Needs QA | Existing Android IA commits on this branch | Shared page skeleton, source/status strip, bottom safety, card reduction. |
| S2 Today cockpit | Needs QA | `05c4febd` plus true-device follow-up | First viewport hierarchy, amount fitting, real next-action priority. |
| S3 Pending queue | Needs QA | `6715c74b` plus current density slice | Queue overview, compact review scan, batch and feedback closure. |
| S4 Ledger density | Needs QA | `1b8fb6bd` plus current ledger density slice | Day grouping, compact record surface, long-list safety. |
| S5 Insights answer flow | Needs QA | `575d9ebf`, `8e4e9d43`, current budget/goal semantics slice | Merchant metric split, sparse/dominant trend handling, answer-first layout, and budget/goal empty-state authority language. |
| S6 Settings governance | In progress | `b61dbedd` plus Settings root, My Devices, and Family Members secondary slices | Root governance and secondary state parity. |
| S7 Debt cleanup and tests | Registered | Later focused slices | Same-page debt only; cross-domain debt stays in registers. |
| S8 True-device review | Registered | Final review doc | Official package, backend pairing, real-data visual QA. |

## Verification Register

| Check | Current state | Next requirement |
| --- | --- | --- |
| Documentation | Phase 0, reference pass, gap register, and this audit register exist; the register now includes page, functional, copy, density, and metric gates. | Keep statuses updated after every slice. |
| Gradle compile/detekt | Current edit-detail keyboard/action slice passes `detektGrayDebug` and `assembleGrayDebug`; detekt still reports the existing compiler-analysis warning but 0 findings. | Rerun flavor-qualified gates after code changes. |
| Unit tests | Today next-action priority, Insights goal header-state decisions, Pending overview, and row-density token decisions have focused JVM tests. The Android test-count baseline is `1237`. | Add focused tests only where state authority or UI decisions are risky. |
| Lint | Required for broader Android slices. | Run before any final Android batch commit/push. |
| True device | Physical device `5c52fc22` installed the official `com.ticketbox` gray package against `https://api.zen70.cn`. Clean online screenshots `80-insights-budget-after-fix.png` and `81-insights-goal-after-fix.png` confirm Budget shows "未设置预算/未启用" and Goals shows "未设置" for zero enabled goals. Screenshot `83-pending-after-density-fix.png` confirms Pending compact mode shows two queue rows in the first viewport without expanded duplicate notices. Screenshot `90-ledger-density-final-settled.png` confirms Ledger header compaction, compact row meta, full amounts, and bottom-nav clearance on live data. Screenshots `95-settings-root-portrait-after-density.png` and `96-settings-root-settled-after-density.png` confirm Settings initial refreshing state and settled confirmed state. The phone was unplugged before final My Devices overflow-menu, Family Members, and edit-detail keyboard screenshots could be captured. | Reconnect physical device and capture Settings Devices, Family Members, and edit amount/currency keyboard state before closing SET-003/SET-004/AIA-024. |
| Screenshots | Local audit folders exist and are intentionally not auto-staged. | Commit only lightweight audit docs unless the user asks to include images. |

## Open Decisions

- Today cockpit still needs true-device review with the user's real large
  monthly amount so the UI never hides the amount behind an ellipsis.
- Product copy needs a release-facing pass. Casual fallback text and engineering
  labels should become calm product states before a page is called done.
- High-frequency merchants are a P0 insight metric issue: the section is not
  acceptable until it is count-ranked and visually distinct from spend ranking.
- Insights should not add a chart dependency until the missing interaction is
  specific: point selection, tooltip, grouped series, zoom, or export preview.
- Settings secondary work should proceed page by page; do not call Settings done
  after only the root page or Sync Status page.
- User-observed secondary-page drift now includes About, Insight Tag/Budget/Goal
  drill pages, Pending real-item rows, and the receipt edit/confirm detail page.
  Treat those as root-cause IA work, not isolated padding defects.
- True-device review remains a release gate for this Android UIUX goal, not an
  optional visual polish step.
