# UI/UX Gap Register

This file records product-design gaps found while polishing the app, especially
when a slice fixes one concrete defect but exposes a nearby page-level follow-up.
It is not a release changelog; close items by linking the commit or handoff entry
that actually ships the fix.

## 2026-07-01

### WEB-2026-07-01-asset-cache-versioning

- Surface: `/web` and `/owner` HTML shells.
- Status: fixed in the current Web/Owner IA slice.
- Gap: static CSS/JS cache invalidation was coupled to `BACKEND_VERSION`, and a
  few shell-critical assets were not versioned at all. Browser sessions could
  therefore keep stale CSS after an IA/layout refactor, making desktop and mobile
  navigation render at the same time.
- Resolution: templates now receive backend-issued `asset_version`, derived from
  the actual `app/static` and `app/templates` content unless a release override is
  explicitly supplied. Tests cover the asset-version contract and changed
  template links.

### WEB-2026-07-01-mobile-secondary-nav-density

- Surface: mobile `/web` secondary pages such as `/web/search`.
- Status: registered follow-up.
- Gap: the mobile primary/secondary IA is now structurally correct, but secondary
  pages open a dense "more" menu that can consume much of the first viewport.
- Desired follow-up: compact the secondary menu into a stronger active-page
  header plus sectioned controls, while keeping deep destinations discoverable
  and preserving the backend-authoritative ledger query parameters.

### OWNER-2026-07-01-dashboard-card-density

- Surface: mobile `/owner`.
- Status: registered follow-up.
- Gap: the Owner dashboard navigation and quick actions are cleaner, but the
  dashboard body still reads more card-heavy than the newer open-section Android
  surfaces.
- Desired follow-up: run a page-level Owner dashboard anti-card pass after the
  Android Settings pass, keeping loopback-only management boundaries intact.

### ANDROID-2026-07-01-secondary-settings-pages

- Surface: Android Settings secondary management pages.
- Status: next active product-design target after pushing the Web/Owner slice.
- Gap: root tabs have received several IA/UIUX passes, but secondary Settings
  pages still need page-by-page visual review, resource-backed copy, and the same
  open-section/anti-card discipline already applied to Today, Pending, Ledger,
  and Insights.
- Constraint: backend remains the authority; Android Room/cache/offline creation
  is client capability, not a competing source of truth.
- Progress 2026-07-02: Background Tasks no longer uses domain-layer hardcoded
  Chinese for task labels; unknown service task/status tokens map to generic
  resource copy, and the page now states that Android only views or requests
  cancellation for service-returned tasks. Recycle Bin now preserves the
  service-returned `short_window_count`, shows a compact overview and divider
  rows instead of one large card, and names read-only, empty, load-failed,
  refreshing, restoring, and restore-confirm states.

### ANDROID-2026-07-01-settings-root-density

- Surface: Android Settings root page.
- Status: implemented in the current Settings root density slice; secondary
  page QA remains open.
- Gap: the root page had the right governance grouping, but navigation rows and
  section titles were too display-heavy. The first viewport read like a large
  directory instead of a compact control center, and initial server-settings load
  could flash as offline before the request had resolved.
- Resolution: Settings root navigation rows now use a quieter body/meta
  hierarchy, section titles use the shared heading weight at body scale, and the
  root authority strip treats first server-settings load as refreshing cache
  state until the backend response confirms or fails. True-device evidence:
  `95-settings-root-portrait-after-density.png` and
  `96-settings-root-settled-after-density.png`.
- Remaining QA: inspect each Settings secondary page individually for the same
  density, state, copy, and bottom-safe behavior.

### ANDROID-2026-07-01-insights-empty-month-authority

- Surface: Android Insights overview and trend tabs.
- Status: fixed in the current Android product-design slice; keep watching in
  screenshot QA.
- Gap: an empty current month could still surface a month-over-month pill and
  historical category comparison, which read like a financial conclusion even
  though backend-authoritative current-month confirmed spend was zero.
- Resolution: empty current months now show an explicit "confirm bills before
  comparison" hint, suppress historical comparison blocks until the current month
  has spend, and keep missing backend supplemental stats as "temporarily
  unavailable" instead of local zero.

### ANDROID-2026-07-01-insights-future-month-authority

- Surface: backend `/api/expenses/months` and Android Insights month filter.
- Status: fixed in the current backend + Android product-design slice.
- Gap: one confirmed expense had a future `expense_time` in 2027, so the
  backend-authoritative month list exposed a future accounting month ahead of
  the real current month. Android then rendered that server list in the month
  picker, which made the product look untrustworthy instead of merely visually
  rough.
- Resolution: the backend month list now caps returned months at the current
  accounting month for the requested timezone. Android also keeps the current
  selected month available as a first option when the backend has no rows for
  it, so an empty current month remains reachable without pretending the backend
  has current-month spending.

### ANDROID-2026-07-01-insights-trend-semantics

- Surface: Android Insights trend charts.
- Status: fixed in the current Android product-design slice.
- Gap: the normal trend state briefly experimented with a chart-library
  rendering before we had a real non-dominant screenshot to judge. The visible
  screenshots did not show a line chart problem; they showed empty-month
  comparison leakage and dominant-peak months that should remain factual
  breakdowns.
- Resolution: dominant peak months still degrade to text-backed breakdowns, while
  normal months use a tokenized native Canvas bar trend. No new Android chart
  dependency is currently needed; revisit a library only when tooltip/zoom,
  multi-metric overlay, or drill-select interactions become real requirements.
- Progress 2026-07-02: the recent 7-day module now adds an explicit previous-3-days
  versus recent-3-days comparison row before the supporting facts, so the reader
  can see direction and scale instead of reading a flat bar strip.

### ANDROID-2026-07-02-refresh-latency-priority

- Surface: Android Today, Pending, Ledger, and Insights refresh.
- Status: implemented in the current frontend latency slice; true-device timing
  still needs capture.
- Gap: refresh could feel slow because non-primary work started before the
  authoritative monthly stats request, and Today kept the pull indicator active
  while Pending refreshed in the background even when existing Pending content
  was already visible.
- Resolution: monthly stats now start before supplemental recurring,
  candidate, data-quality, lifestyle, and confirmed-cache work; Today starts
  the month refresh before Pending; Today, Pending, and Ledger stop holding the
  whole-page pull indicator once readable content is already on screen.
  Confirmed-ledger sync now requests the backend-supported 200 rows per page
  instead of 50 to reduce avoidable round trips on larger ledgers.

### ANDROID-2026-07-01-ledger-empty-safe-area

- Surface: Android Ledger empty state.
- Status: fixed in the current Android product-design slice; verify on real
  device after install.
- Gap: the empty-state primary actions could sit under the floating bottom nav on
  tall real-device screenshots, making the page look unfinished and risking
  missed taps.
- Resolution: the empty state now adds its own bottom safety space on top of the
  shared scroll scaffold padding, so the manual-entry/sync actions remain visibly
  above the bottom nav.

### ANDROID-2026-07-01-product-reference-ia-contract

- Surface: Android Today, Pending, Ledger, Insights, and Settings.
- Status: registered contract for the ongoing Android IA/UIUX refactor.
- Gap: prior passes could still drift into "polish the existing cards" instead
  of judging the five tabs from product responsibility first. This made Insights
  especially vulnerable to becoming a chart container rather than an answer page.
- Reference pass: YNAB, Monarch, Lunch Money, Qianji, Shark Accounting,
  Suishouji, and Material Design chart/design-token guidance were reviewed and
  condensed into `docs/current/ANDROID_UIUX_IA_REFERENCE_2026-07-01.md`.
- Product rule: Today is the daily cockpit, Pending is the inbox, Ledger is the
  confirmed-record surface, Insights is the answer/analysis page, and Settings is
  governance. Root screens must share shell language but not collapse into the
  same card pattern.

### ANDROID-2026-07-01-insights-feature-gaps

- Surface: Android Insights and its Ledger drill-through.
- Status: registered follow-up.
- Gap: the current rebuild improves sparse-data reading, but mature finance
  products also support saved report presets, point/bar selection, month-review
  framing, and direct inspection of the transactions behind a chart.
- Desired follow-up: add drillable insight sections backed by backend-authority
  ledger queries; then introduce saved report presets only after the query
  contract is explicit and test-covered.

### ANDROID-2026-07-01-insights-budget-goal-state

- Surface: Android Insights Budget and Goals tabs.
- Status: fixed in the current Android Insights IA slice; true-device evidence
  captured as `80-insights-budget-after-fix.png` and
  `81-insights-goal-after-fix.png` under the local audit folder.
- Gap: the Budget tab reused generic monthly insight rows when no budget was
  configured, and the Goals tab labeled zero enabled goals as "stable". Both
  states made missing configuration look like a real financial conclusion.
- Resolution: Budget now branches on backend-derived `BudgetProgress`; missing
  budgets show "未设置预算 / 未启用" and a setup entry. Goals now uses a small
  Empty / Attention / Stable state model, so "节奏稳定" only appears when at
  least one real goal exists and none need attention.

### ANDROID-2026-07-01-phase0-ia-uiux-audit

- Surface: Android Today, Pending, Ledger, Insights, Settings root, and Settings
  secondary pages.
- Status: active contract for the updated Android IA/UIUX goal; execution is
  tracked in `docs/current/ANDROID_UIUX_AUDIT_REGISTER_2026-07-01.md`.
- Gap: the user explicitly reset the goal from page-level polish to a full
  product-design-lead refactor. Continuing to tune individual cards would not
  be enough; the five root pages need a shared skeleton, distinct product jobs,
  backend-authority state language, and a reviewable slice plan before more UI
  implementation lands.
- Resolution target: `docs/current/ANDROID_IA_UIUX_PHASE0_AUDIT_2026-07-01.md`
  records the Phase 0 audit, page matrix, data-authority rules, Insights chart
  contract, and commit slicing plan. The audit register records per-page status,
  acceptance gates, Settings secondary coverage, and true-device review debt.

### ANDROID-2026-07-01-pending-queue-overview

- Surface: Android Pending root page.
- Status: implemented in the current Pending queue slice; density pass verified
  on true-device screenshot `83-pending-after-density-fix.png`.
- Gap: the queue counts were already real, but they were split between the page
  header, filters, and a filtered-only bulk-confirm entry. That made the page
  feel like a list plus controls instead of a review inbox with an obvious
  processing order.
- Resolution: Pending now shows an open queue overview derived from `state.items`
  before the filters. It prioritizes suspected duplicates, missing amount,
  missing merchant, and directly confirmable items, and exposes the batch-confirm
  entry without inventing any counts or treating cached data as server truth.
  Compact mode no longer expands duplicate-warning blocks or inline action
  buttons, so the first viewport supports queue scanning instead of full-detail
  reading.
- Remaining QA: continue official-package review for cache/read-only copy,
  scroll position, bottom-nav safety, and the Comfortable detail mode.

### ANDROID-2026-07-01-today-cockpit-priority

- Surface: Android Today root page.
- Status: implemented in the current Today cockpit slice; needs true-device QA.
- Gap: Today already had real pending and monthly state, but the first viewport
  still let the month total, action buttons, and work queue compete. Large
  amounts also needed a stronger width guarantee so they do not visually collapse
  into truncation on narrow phones.
- Resolution: Today now gives the monthly amount a full-width line with
  auto-sizing down to a smaller floor, shows the month source/status beside the
  confirmed count, and derives one primary next action from real pending counts
  before falling back to upload or ledger review. Read-only state does not prompt
  write actions.
- Remaining QA: run official-package true-device review for amount fitting,
  first-viewport density, source/status copy, and bottom-nav scroll behavior.

### ANDROID-2026-07-01-ledger-long-list-density

- Surface: Android Ledger confirmed-history list.
- Status: implemented in the current Ledger density slice; multi-day sample QA
  remains open.
- Gap: a long ledger with many days can force endless vertical scanning if every
  day and every expense is fully expanded. That fights the new mature-product
  direction and makes the Ledger page feel like stacked cards instead of a dense
  record surface.
- Resolution: the Ledger header now keeps summary, count, and manual entry in a
  tighter two-row structure; the default record row uses compact density tokens,
  shows `time · category` under the merchant instead of repeating full dates,
  keeps amounts complete, and preserves tap/long-press edit selection paths.
  True-device evidence: `90-ledger-density-final-settled.png`.
- Remaining QA: verify many-day backend data to tune day folding and scroll depth
  without hiding confirmed records.

### ANDROID-2026-07-01-settings-secondary-state-parity

- Surface: Android Settings secondary pages.
- Status: registered follow-up in the Settings slice.
- Gap: many secondary pages already use `SettingsPageFrame`, status banners, and
  resource-backed copy, but state coverage is uneven across connection, sync,
  devices, members, rules, merchants, tags, recycle bin, export, security,
  appearance, and background tools.
- Progress 2026-07-01: the Sync Status page now has a dedicated state overview
  for queued, conflict, and failed offline mutations. My Devices now uses
  compact scan-first rows, overflow device actions, resource-backed loading
  copy, and a device-specific missing-activity label instead of the generic
  `未填写时间`. Family Members now keeps role/status visible and moves
  role/owner/disable actions into an overflow menu, with product loading copy
  for members and audit records. Recycle Bin now uses backend-provided
  short-window counts, explicit read-only/failed/empty/restoring states, and a
  scan-first divider list rather than a large container. Final true-device
  screenshots are still pending because the phone was unplugged before the last
  visual pass. The remaining Settings secondary pages still need page-by-page
  state parity review.
- Desired follow-up: make every secondary page declare loading, empty, error,
  read-only, cached/offline/direct-only, success, and destructive-confirmation
  behavior with the shared Settings skeleton.

### ANDROID-2026-07-02-recycle-bin-secondary-parity

- Surface: Android Settings -> Recycle Bin.
- Status: implemented locally; true-device evidence still pending.
- Gap: the Recycle Bin page had the right backend endpoint, but Android dropped
  the backend `short_window_count`, inferred urgency from the localized
  retention label, and wrapped the list/empty/refresh states in a single large
  panel. Read-only and load-failed states were not visible enough for a
  governance page.
- Resolution: repository and ViewModel now carry a `RecycleBinSnapshot` with
  backend-provided short-window count; the page shows a compact summary,
  explicit read-only/empty/load-failed states, divider rows, confirm-before-
  restore, and resource-backed copy.
- Remaining QA: capture empty, populated, restoring, and viewer/read-only states
  on a physical device after installing the official package.

### ANDROID-2026-07-01-secondary-page-language-drift

- Surface: Android Settings secondaries, Insights Tag/Budget/Goal drill pages,
  and other second-level Android surfaces.
- Status: user-observed follow-up; true-device evidence pending because the
  phone was unplugged before this pass.
- Gap: root tabs are moving toward one product skeleton, but second-level pages
  can still feel like a different app: heavier rounded containers, uneven page
  rhythm, inconsistent status language, and capsule text that does not sit
  cleanly inside its container.
- Desired follow-up: define the secondary-page skeleton as a first-class
  product pattern, then close pages one by one. Each page needs the same title,
  back, state, section, row-density, chip/button alignment, and bottom-safe
  behavior as the root tabs while keeping its own product job clear.

### ANDROID-2026-07-01-insights-budget-goal-drill-semantics

- Surface: Android Insights Budget, Goals, and Tag/drill pages.
- Status: partially implemented; true-device QA and product/API follow-up remain.
- Gap: user observation says the Budget/Tag area can still show mismatched
  monthly-insight modules, unclear budget remaining/options language, and goal
  wording that does not make the target type obvious. "Goal enabled" is too vague
  for a finance product; repayment, saving, and spending-control goals have
  different user intent.
- Resolution so far: Budget secondary pages now treat backend `configured=false`
  as not enabled and hide active-only budget modules. Goal rows now label existing
  backend-backed types as "开销目标" or "还债目标" instead of a generic enabled
  target. Tag-filtered Insights now disables global Budget/Goals tabs and keeps
  tag views to tag-relevant Overview/Trend/Category content.
- Desired follow-up: audit the actual drill paths with backend data. Budget
  still needs true-device coverage for active, over-budget, read-only, and not
  enabled states. Saving goals remain a product/API contract gap; Android must
  not invent a "存款目标" type until the backend exposes it.

### ANDROID-2026-07-01-about-product-trust-page

- Surface: Android Settings -> About Ticketbox.
- Status: implemented locally; true-device evidence pending because the phone is
  unplugged.
- Gap: the About page is part of the product trust layer, but it has not yet had
  the same secondary-page treatment as Devices or Members. It risks reading like
  a diagnostics surface if build/support/legal details are not structured and
  copy-reviewed.
- Resolution: About now uses a compact trust-page layout with resource-backed
  app/version, confirmation boundary, sync authority, and screenshot/OCR boundary
  rows. Release-facing copy avoids backend/local implementation wording.
- Remaining QA: capture About on a physical device and check row density,
  icon/text alignment, and bottom spacing.

### ANDROID-2026-07-01-pending-real-item-card-density

- Surface: Android Pending real unconfirmed-bill rows.
- Status: implemented locally; true-device evidence still pending.
- Gap: compact-mode summary work improved the top of Pending, but user
  observation says real unconfirmed items can still feel like the old Ledger
  card stack. That means the default row surface still needs a scan-first pass,
  not only the overview.
- Resolution: default Pending rows now use a dedicated scan-first review row
  instead of reusing the generic expense card. The row keeps thumbnail/category,
  merchant, time, true issue signals, full amount, and the next action visible
  from the same `Expense` state.
- Remaining QA: reconnect a physical device with real pending items and verify
  density, amount fitting, swipe actions, read-only state, and offline/cache
  labels.

### ANDROID-2026-07-01-edit-keyboard-action-density

- Surface: Android receipt edit / confirm detail page.
- Status: root-cause fix implemented locally; true-device evidence still
  pending.
- Gap: user screenshot `Screenshot_2026-07-01-23-48-19-093_com.ticketbox.jpg`
  shows the amount/currency field with the keyboard open. The bottom action
  surface becomes a large rounded block, the four actions form a heavy 2x2 grid,
  and the amount section still looks like the older card-first language.
- Resolution: `AppPageScrollableColumn` captures IME visibility before the
  scaffold consumes keyboard insets, and the amount field now forces compact
  actions while focused for devices that under-report IME state. The currency
  selector is a single-line scrollable chip row and all touched labels remain in
  resources.
- Remaining QA: capture the same amount/currency keyboard state on a physical
  device and confirm the strip does not crowd, truncate, or cover the input.

### ANDROID-2026-07-02-refresh-loading-latency

- Surface: Android Today, Pending, Ledger, and Insights root refresh.
- Status: implemented locally; true-device timing evidence still pending.
- Gap: user reports frontend refresh/loading is too slow. The root cause found in
  the Android state path is that page-level loading could stay active while
  non-primary work continued after the main monthly stats response was already
  available.
- Resolution: monthly stats now clears the page loading state as soon as the
  authoritative monthly stats response is applied. Lifestyle stats and confirmed
  cache sync continue in the background. Insights reports now release the trend
  loading state as soon as the overview response lands; goals continue as a
  secondary background result and stale goal requests are cancelled. Pending and
  Ledger now keep existing rows readable while the authority strip shows refresh
  state, and confirmed-ledger sync uses 200 rows per page.
- Remaining QA: measure Today, Pending, Ledger, and Insights pull-to-refresh on
  a physical device with the production backend and confirm the page does not
  imply fresh backend truth before the primary response lands.

### ANDROID-2026-07-01-insights-frequent-merchant-metric

- Surface: Android Insights merchant sections.
- Status: implemented in Android; true-device QA still pending for the visible
  merchant rows.
- Gap: "高频商家" must mean count-ranked merchants, not amount-ranked merchants
  wearing a frequency label. The backend has two different contracts:
  `stats/lifestyle.frequent_merchants` is count-ranked, while
  `reports/overview.merchant_ranking` defaults to amount ranking unless
  `ranking_metric=count` is requested.
- Resolution: Android requests Reports overview with `ranking_metric=count`,
  renders the ranking title/value from the returned metric, and keeps amount as
  supporting context for frequency rows. Final closeout still needs a live
  Insights screenshot with populated merchant rows.

### ANDROID-2026-07-01-root-page-density

- Surface: Android Today, Pending, Ledger, Insights, and Settings root pages.
- Status: registered acceptance gate in the Android audit register.
- Gap: the product direction is "mature daily workbench", but several screens
  can still feel dense because summary, filters, tools, charts, and records all
  compete near the top. Fixing one card or button does not close the page.
- Desired follow-up: each root page needs one first-read story, a restrained
  tool row, clear section rhythm, and fewer large rounded containers. Verify on
  a real phone, because desktop/code review does not expose first-viewport
  crowding, bottom-nav overlap, or narrow-width truncation.

### ANDROID-2026-07-01-number-layout-truncation

- Surface: Android Today, Ledger, Insights, Settings summaries, and merchant /
  category rankings.
- Status: registered acceptance gate in the Android audit register.
- Gap: large money values and metric labels can lose trust instantly if the
  important number becomes an ellipsis. The user's real data already exposed
  this risk on Today.
- Desired follow-up: use full-width numeric lanes, responsive text sizing,
  stable row metrics, and true-device screenshots for large amounts. The main
  amount/count/date on a row must remain readable before decorative text.

### ANDROID-2026-07-01-product-copy-tone

- Surface: Android offline/cache/error/read-only/sync copy across all pages.
- Status: registered acceptance gate in the Android audit register.
- Gap: fallback language can drift into casual or engineering phrasing. That
  makes a finance app feel less trustworthy even when the data source is
  technically correct.
- Desired follow-up: all touched visible strings stay in resources and use
  release-facing state language: updated, offline data, waiting to sync, sync
  failed, read-only, retry, unavailable. Avoid casual phrases and avoid exposing
  backend/local implementation wording to ordinary users.

### ANDROID-2026-07-01-insights-drill-and-presets

- Surface: Android Insights, Ledger filters, and backend report contracts.
- Status: deferred feature gap.
- Gap: readable charts and rankings are only half of the insight loop. A mature
  finance product lets the user inspect the bills behind a peak, merchant,
  category, or report view, and often save repeated report setups.
- Desired follow-up: register and implement backend-authoritative ledger query
  contracts before adding chart-point drill or saved report presets. Android
  must not synthesize authoritative report results locally.

### ANDROID-2026-07-02-connection-vpn-trust

- Surface: Android Settings connection page and network error feedback.
- Status: Android authority-state fix landed locally; VPN true-device evidence
  still pending.
- Gap: the connection page now makes the bound address and cache/confirmed state
  visible, but the user-observed VPN failure still needs real-device evidence and
  network-path diagnosis. A polished state page is not proof that VPN routing,
  split-tunnel behavior, DNS, or certificate interception is handled correctly.
- Progress 2026-07-02: the Connection page now only treats server settings as
  confirmed when `serverSettingsFresh=true`; stale settings remain a marked
  cache fallback instead of lighting the confirmed state after refresh failure.
- Desired follow-up: reproduce with the official package on a physical device,
  capture online, VPN-on, VPN-off, and offline states, and ensure user-facing
  copy tells the user what changed without exposing repository or transport
  internals. Backend remains the authority whenever reachable; cache display is
  only a marked fallback.
