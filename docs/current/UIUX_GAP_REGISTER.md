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
