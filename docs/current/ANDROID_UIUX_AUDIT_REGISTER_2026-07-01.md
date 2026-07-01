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
| Verification | Relevant unit/Compose/ViewModel tests, detekt/lint/build, and true-device or emulator evidence are recorded. |

## Page Register

| ID | Surface | Status | Priority | Finding | Acceptance |
| --- | --- | --- | --- | --- | --- |
| AIA-001 | Global shell | Needs QA | P0 | The five root pages have a shared shell, but the final true-device pass must verify header rhythm, status language, bottom padding, and dense pages together. | Today, Pending, Ledger, Insights, and Settings share one skeleton language without becoming the same card layout. |
| AIA-002 | Data authority | Needs QA | P0 | Backend authority and local cache labels exist, but every page must keep cached/offline state below server facts. | Fresh backend, local cache, read-only, queued, conflict, and failed states are visibly distinct and never imply fake server truth. |
| AIA-003 | Today | Needs QA | P0 | Today now gives the month amount full width, includes the source/status in the month line, and derives a single next action from real pending state; true-device review still needs to judge density and amount fitting with live data. | The first screen states source, pending workload, month status, and next action without truncating large amounts. |
| AIA-004 | Pending | Needs QA | P0 | Pending now has a real queue overview derived from `state.items`; true-device review still needs to judge density, first-viewport balance, and scroll behavior. | No fake duplicate/ready counts; the user can immediately see ready, missing amount, missing merchant, duplicate, and blocked work. |
| AIA-005 | Ledger | Needs QA | P0 | Long history can become endless scrolling if day groups and compact rows are not tuned on real data. | Confirmed records scan by day/month with compact rows, useful filters, no bottom-nav obstruction, and no large-card pile. |
| AIA-006 | Insights root | Needs QA | P0 | Insights has been reshaped, but it still needs final review as an answer page rather than a chart dashboard. | The page answers spend, comparison, recent signal, top contributors, and action signals in that order. |
| AIA-007 | Insights charts | Needs QA | P0 | Recent 7-day and month trend views must show comparison, variation, concentration, or degrade to facts. | No chart exists only as decoration; dominant or sparse data becomes facts/ranking, not flat bars or fake lines. |
| AIA-008 | Insights merchants | Needs QA | P0 | High-frequency merchants and spend-ranked merchants must stay separate. | Frequency lists sort by confirmed count; spend lists sort by amount; each row shows the active metric clearly. |
| AIA-009 | Settings root | Registered | P1 | Settings should read as governance, not a directory. | Account, ledger/family, device, connection/sync, data rules, safety, and appearance are grouped by responsibility. |
| AIA-010 | Settings secondaries | In progress | P1 | Secondary pages are uneven. Sync status has improved, but other pages still need page-by-page state parity. | Each secondary page has consistent title, back, explanation, loading, empty, error, cached/offline, read-only, success, and destructive states. |
| AIA-011 | Copy and resources | Registered | P0 | New Android UI copy must not be hardcoded, and product copy must avoid engineering phrasing. | Touched user-visible strings live in `res/values/*.xml`; grep review finds no new hardcoded Chinese/English UI copy. |
| AIA-012 | Interaction closure | Registered | P0 | Confirm/reject/edit/undo/retry/read-only paths need consistent feedback across Today, Pending, Ledger, and Settings. | Every write action shows success/failure/queued/conflict and gives retry or recovery where applicable. |
| AIA-013 | Chart dependencies | Fixed | P1 | Android Vico was previously allowed but later retired for the current chart need. Future dependency work must not be aesthetic-only. | Native Canvas/token charts remain current; new chart dependency requires ADR-0023 review, official metadata, size/accessibility impact, and fallback. |
| AIA-014 | True-device review | Registered | P0 | The official package must be checked on a real phone after the audit-led slices, not only by code review. | Backend is started, official `com.ticketbox` is bound by pairing code, and screenshots/notes cover scroll, clipping, keyboard, nav, dark/light, and current real data. |

## Secondary Settings Register

| ID | Page | Status | Required closeout |
| --- | --- | --- | --- |
| SET-001 | Connection | Registered | Fresh/backend failure/cache states, reconnect path, no exposed token/server internals in ordinary copy. |
| SET-002 | Sync status | Fixed | Queued, conflict, and failed offline mutations are summarized from real outbox state. |
| SET-003 | Devices | Registered | Device role/status/revoke flows distinguish server authority from local device cache. |
| SET-004 | Members | Registered | Role, invite, remove, read-only, and permission-denied states are explicit. |
| SET-005 | Join family | Registered | Pairing/invite flow has clear loading, failure, expired, success, and back behavior. |
| SET-006 | Category rules | Registered | Rule list and edit states handle empty, conflict, queued, failed, read-only, and stale data. |
| SET-007 | Merchant management | Registered | Alias/catalog actions show conflicts and do not rewrite historical facts silently. |
| SET-008 | Tags | Registered | Rename/merge/conflict states follow backend contract and resource-backed copy. |
| SET-009 | Recycle bin | Registered | Restore/delete states make destructive behavior and backend authority clear. |
| SET-010 | Export/data tools | Registered | Export scope, failure, empty, progress, and local file states are explicit. |
| SET-011 | Security | Registered | Local biometric/token language stays separate from server authorization. |
| SET-012 | Background tasks | Registered | Worker status is local capability only and does not imply server processing. |
| SET-013 | Appearance/background | Registered | Preview/crop/apply flows are bottom-safe, reversible, and not visually isolated from the product system. |
| SET-014 | About | Registered | Version/build/support copy stays product-level and does not expose diagnostics in release-facing text. |

## Slice Register

| Slice | Status | Commit or target | Scope |
| --- | --- | --- | --- |
| S0 Audit and reference | Fixed | `a66393e3`, `0a829305` | Phase 0 audit, product references, initial gap register. |
| S1 Shared shell / authority language | Needs QA | Existing Android IA commits on this branch | Shared page skeleton, source/status strip, bottom safety, card reduction. |
| S2 Today cockpit | Needs QA | Current Today cockpit slice | First viewport hierarchy, amount fitting, real next-action priority. |
| S3 Pending queue | Needs QA | Current Pending queue slice | Queue overview, compact review scan, batch and feedback closure. |
| S4 Ledger density | Needs QA | `1b8fb6bd` | Day grouping, compact record surface, long-list safety. |
| S5 Insights answer flow | Needs QA | `575d9ebf`, `8e4e9d43` | Merchant metric split, sparse/dominant trend handling, answer-first layout. |
| S6 Settings governance | In progress | `b61dbedd` plus next settings slices | Root governance and secondary state parity. |
| S7 Debt cleanup and tests | Registered | Later focused slices | Same-page debt only; cross-domain debt stays in registers. |
| S8 True-device review | Registered | Final review doc | Official package, backend pairing, real-data visual QA. |

## Verification Register

| Check | Current state | Next requirement |
| --- | --- | --- |
| Documentation | Phase 0, reference pass, gap register, and this audit register exist. | Keep statuses updated after every slice. |
| Gradle compile/detekt | Today cockpit slice passes `compileGrayDebugKotlin`, `detektGrayDebug`, and `detektGrayDebugUnitTest` with the existing detekt alpha warning and 0 findings. | Rerun flavor-qualified gates after code changes. |
| Unit tests | Today next-action priority has focused JVM tests and the Android test-count baseline is updated to `1237`. | Add focused tests only where state authority or UI decisions are risky. |
| Lint | Required for broader Android slices. | Run before any final Android batch commit/push. |
| True device | Prior real-device passes exist, but the current audit register still needs a final clean pass. | Bind official `com.ticketbox` to backend and capture fresh evidence after page slices. |
| Screenshots | Local audit folders exist and are intentionally not auto-staged. | Commit only lightweight audit docs unless the user asks to include images. |

## Open Decisions

- Today cockpit still needs true-device review with the user's real large
  monthly amount so the UI never hides the amount behind an ellipsis.
- Insights should not add a chart dependency until the missing interaction is
  specific: point selection, tooltip, grouped series, zoom, or export preview.
- Settings secondary work should proceed page by page; do not call Settings done
  after only the root page or Sync Status page.
- True-device review remains a release gate for this Android UIUX goal, not an
  optional visual polish step.
