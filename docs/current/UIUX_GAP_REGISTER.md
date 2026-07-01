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
- Status: implemented in the current Pending queue slice; needs true-device QA.
- Gap: the queue counts were already real, but they were split between the page
  header, filters, and a filtered-only bulk-confirm entry. That made the page
  feel like a list plus controls instead of a review inbox with an obvious
  processing order.
- Resolution: Pending now shows an open queue overview derived from `state.items`
  before the filters. It prioritizes suspected duplicates, missing amount,
  missing merchant, and directly confirmable items, and exposes the batch-confirm
  entry without inventing any counts or treating cached data as server truth.
- Remaining QA: run official-package true-device review for first-viewport
  density, cache/read-only copy, scroll position, and bottom-nav safety.

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
- Status: active in current worktree; verify before commit.
- Gap: a long ledger with many days can force endless vertical scanning if every
  day and every expense is fully expanded. That fights the new mature-product
  direction and makes the Ledger page feel like stacked cards instead of a dense
  record surface.
- Desired follow-up: finish and verify day grouping/folding, compact rows, and
  bottom-safe empty states against backend-authoritative ledger data.

### ANDROID-2026-07-01-settings-secondary-state-parity

- Surface: Android Settings secondary pages.
- Status: registered follow-up in the Settings slice.
- Gap: many secondary pages already use `SettingsPageFrame`, status banners, and
  resource-backed copy, but state coverage is uneven across connection, sync,
  devices, members, rules, merchants, tags, recycle bin, export, security,
  appearance, and background tools.
- Progress 2026-07-01: the Sync Status page now has a dedicated state overview
  for queued, conflict, and failed offline mutations. The remaining Settings
  secondary pages still need page-by-page state parity review.
- Desired follow-up: make every secondary page declare loading, empty, error,
  read-only, cached/offline/direct-only, success, and destructive-confirmation
  behavior with the shared Settings skeleton.

### ANDROID-2026-07-01-insights-frequent-merchant-metric

- Surface: Android Insights merchant sections.
- Status: P0 registered follow-up in the Insights slice.
- Gap: "高频商家" must mean count-ranked merchants, not amount-ranked merchants
  wearing a frequency label. The backend has two different contracts:
  `stats/lifestyle.frequent_merchants` is count-ranked, while
  `reports/overview.merchant_ranking` defaults to amount ranking unless
  `ranking_metric=count` is requested.
- Desired follow-up: split the merchant IA clearly: high-frequency merchants are
  sorted by confirmed count, spend-ranked merchants are sorted by amount, and
  each row makes the active metric obvious with the other metric as supporting
  context.

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
