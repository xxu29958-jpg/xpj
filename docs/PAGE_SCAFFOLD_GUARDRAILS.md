# Page Scaffold Guardrails

This phase is mandatory before reusable visual components, theme visuals, or page visual restoration.

## Scope

Allowed changes:

- Add or organize `AppPageScaffold`, `AppPageHeader`, `AppScrollableContent`, `BottomBarAwarePadding`, `PageRole`, and `PageDensity`.
- Unify status bar handling, navigation bar avoidance, horizontal padding, page header start position, header-to-content gap, and scroll bottom padding.
- Remove or replace large per-screen `Spacer` blocks that push content down.
- Wire the real Pending, Ledger, Stats, Settings, and Edit screens into the scaffold.

Forbidden changes:

- Do not redesign cards, buttons, backgrounds, Hero cards, or theme visuals in this phase.
- Do not change business logic, ViewModels, repositories, API calls, Room cache, OCR, duplicate handling, CSV export, server binding, or category rules.
- Do not use random per-screen bottom padding values.

## Density

- Pending: comfortable.
- Stats: comfortable.
- Settings: comfortable.
- Ledger: compact.
- Edit: compact.

Ledger is a reading page. Edit is a task page. Their priority is readable amounts, merchants, times, categories, form fields, and primary actions.

## Defaults

- `horizontalPadding = 24.dp`
- `compact.topContentPadding = 16.dp`
- `comfortable.topContentPadding = 24.dp`
- `compact.headerToContentGap = 16.dp`
- `comfortable.headerToContentGap = 22.dp`
- `compact.sectionGap = 18.dp`
- `comfortable.sectionGap = 24.dp`
- `cardGap = 16.dp`
- `bottomContentExtraPadding = 24.dp`

Bottom padding formula:

```text
scrollContentBottomPadding =
  bottomBarHeight + navigationBarsPadding + bottomContentExtraPadding
```

If the bottom bar cannot be measured in the first pass, use `AppPageDefaults.BottomBarHeight` as a named estimate and replace it later with measured layout data.

## Acceptance

- `AppPageScaffold`, `AppPageHeader`, and `AppScrollableContent` are not dead components.
- Pending, Ledger, Stats, Settings, and Edit are wired into the scaffold.
- Before and after screenshots are compared for reduced top whitespace, less content sinking, better bottom avoidance, and stable bottom navigation.
- Titles are not clipped.
- Pages are not overly empty at the top.
- The final scroll item can move fully above the floating bottom navigation.
- Ledger and Edit readability does not regress.

## Test Plan

Use the project variant:

- Prefer `assembleGrayDebug`, `testGrayDebugUnitTest`, and `lintGrayDebug`.
- If gray does not exist, fall back to `assembleDebug`, `testDebugUnitTest`, and `lintDebug`.

Screenshot acceptance targets:

- `pending_empty.png`
- `ledger_items.png`
- `stats_empty.png`
- `settings_root.png`
- `expense_edit.png`

