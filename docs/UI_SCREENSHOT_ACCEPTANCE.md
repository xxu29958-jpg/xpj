# UI Screenshot Acceptance

Date: 2026-05-06

Device: Xiaomi 15 Pro, real device over ADB

Variant: `grayDebug`

Scope: design-system / page-scaffold / visual polish acceptance. This document records real-device screenshots captured after the current Android UI pass. Large screenshots stay under `artifacts/` and are not committed.

## Verified Screenshots

| Target | Artifact | Status | Notes |
| --- | --- | --- | --- |
| Pending empty | `artifacts/pending_empty.png` | Captured | Pending benchmark empty state with hero, upload CTA, upload flow, and empty card. |
| Pending with items | `artifacts/pending_with_items.png` | Captured | Real pending items captured after upload; upload flow guide is hidden in item mode, compact bill cards keep the first bill actions visible above the floating bottom nav. |
| Pending offline | `artifacts/pending_offline.png` | Captured | Shows network fallback as a light product state; title is not covered by loading. |
| Ledger with items | `artifacts/ledger_items.png` | Captured | Ledger remains readable with compact filter area and visible list. |
| Ledger search empty | `artifacts/ledger_search_empty.png` | Captured | Search empty state captured with a nonsense query. |
| Stats empty | `artifacts/stats_empty.png` and `artifacts/stats_current.png` | Captured | Empty state includes lightweight skeleton placeholders and primary refresh CTA. |
| Stats with data | `artifacts/stats_with_data.png` | Captured | Real monthly totals and trend card captured on first entry with local ledger-backed fallback, then refreshed by remote stats when available. |
| Settings root | `artifacts/settings_root.png` | Captured | Settings uses secondary-page entry structure and unified entry card styling. |
| Appearance | `artifacts/appearance.png` | Captured | Theme grid and appearance structure captured; secondary-page back/header spacing is tightened so the page title no longer feels pushed down. |
| Background gallery | `artifacts/background_gallery.png` | Captured | Built-in background catalog and categories captured. |
| Background preview | `artifacts/background_preview.png` | Captured | Preview confirms page-effect preview before applying. |
| Expense edit | `artifacts/expense_edit.png` | Captured | Edit screen remains compact and readable. |

## Current Follow-Up Notes

| Target | Note | Required Follow-Up |
| --- | --- | --- |
| Pending with items | Captured from the current real device state with 3 pending expenses. A Xiaomi floating system control overlaps part of the lower card in the screenshot; it is not App UI. | Re-capture after disabling the phone floating control if a clean marketing/PR screenshot is needed. |
| Stats with data | Captured from the current local confirmed cache on first entry; remote stats can still refresh over it. | If local and remote totals diverge, investigate sync freshness rather than visual layout. |
| Expense edit | Image preview can show a short loading placeholder before the protected screenshot appears. | Current real-device wait capture confirms the screenshot resolves and remains opt-in for full-size viewing. |

## Page Scaffold Follow-Up - 2026-05-06

- `AppPageDefaults.BottomBarHeight` is now the named scaffold constant from the Page Scaffold Gate (`72.dp`) instead of a per-screen bottom-padding guess.
- Pending item cards were tightened only in compact preview mode so the edit / confirm / ignore actions remain visible above the floating bottom bar.
- Latest real-device check: `artifacts/pending_compact_card_polish.png`, copied to `artifacts/pending_with_items.png` for the current acceptance set.
- No ViewModel, Repository, backend API, Room, OCR, duplicate, CSV, upload, or token flow changed in this scaffold polish.

## Scaffold Recheck - 2026-05-06 21:38

Real-device check artifacts:

- `artifacts/current_pending_check.png`
- `artifacts/current_ledger_check.png`
- `artifacts/current_stats_check.png`
- `artifacts/current_settings_check.png`
- `artifacts/current_expense_edit_check.png`

Observed result:

- Pending: title area is not covered, compact item actions remain above the floating bottom navigation.
- Ledger: compact density keeps the title, summary, filters, and first list items readable without status-bar clipping.
- Stats: title and month selector are safe, overview content scrolls behind the floating bottom bar as intended.
- Settings: root entries keep enough bottom clearance for the floating bottom navigation.
- Expense Edit: compact task layout keeps amount, merchant, category, and primary work area readable.

## Commands Used

```powershell
cd E:\projects\xiaopiaojia\android
.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
.\gradlew.bat --no-daemon :app:lintGrayDebug
.\gradlew.bat --no-daemon :app:assembleGrayDebug
```

All three commands passed for the current `grayDebug` variant before this acceptance record was written.

Full project verification was also run after the screenshot pass:

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_project.ps1
```

Result:

- Backend `compileall`: passed.
- Backend `ruff check app scripts tests`: passed.
- Backend `pytest`: 38 passed.
- Backend `scripts\smoke_test.py`: passed.
- Android `:app:testGrayDebugUnitTest`: passed.
- Android `:app:assembleGrayDebug :app:assembleInternalDebug`: passed.
- Android `:app:lintGrayDebug`: passed.

Gray release acceptance was then run with a temporary local keystore:

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\accept_gray_release.ps1 -SkipProjectVerify -UseTemporaryKeystore -Serial c16cd054 -Adb E:\projects\xiaopiaojia\.toolchains\android-sdk\platform-tools\adb.exe
```

Result:

- Script exited successfully.
- Public upload acceptance used the configured tokens, created test pending records through both iOS and Android upload endpoints, and cleaned them up via `reject`.
- Windows diagnosis, public endpoint checks, and release build checks passed.
- `android/app/build/outputs/apk/gray/release/app-gray-release.apk` was generated.
- Latest `grayDebug` was installed and launched on the attached device.

## Acceptance Notes

- Page scaffold and bottom-bar avoidance are active on Pending, Ledger, Stats, Settings, Appearance, Background Gallery/Preview, and Expense Edit.
- Settings secondary pages now group the back action and page header more tightly, reducing the visible top gap without changing any settings behavior.
- Pending item mode now prioritizes real bills over the upload-flow guide; the guide remains available for empty state.
- Pending remains the benchmark page; the current screenshot is suitable for human review.
- Ledger and Expense Edit are kept more solid and compact than Pending/Stats, preserving readability over immersion.
- Background and theme flows are captured as local UI customization only; no background image is uploaded to the backend.
- No backend API, repository, Room, OCR, duplicate, CSV, upload, or token flow was changed during this acceptance pass.

## Pending Hero Polish - 2026-05-07

Real-device check artifact:

- `artifacts/pending_hero_polish_v2.png`
- copied to `artifacts/current_pending_check.png`

Observed result:

- Pending hero status changed from tall stacked tiles to two horizontal glass metrics for real values: pending count and suspected duplicate count.
- The failed three-tile attempt was rejected because Chinese labels wrapped vertically on the real device.
- Hero height is lower than the previous stacked version, so the first pending bill and its actions remain visible above the floating bottom navigation.
- Upload remains the primary CTA, and the product boundary copy remains unchanged: screenshots and OCR drafts do not auto-enter the ledger.
- No ViewModel, Repository, backend API, Room, OCR, duplicate, CSV, upload, or token flow changed in this polish.

## Appearance Theme Visuals - 2026-05-07

Real-device check artifact:

- `artifacts/appearance_theme_visuals.png`
- copied to `artifacts/appearance.png`

Observed result:

- Theme cards now use `ThemeVisuals` for container tint, selected border/shadow, preview hero gradient, and chip accents instead of only the Material `ColorScheme`.
- The preview cards read more like miniature App surfaces: atmosphere layer, hero strip, glass summary strip, and small accent markers.
- Harbor remains visibly recommended/current without turning the whole settings page into a high-contrast demo.
- The background and theme flow remains local UI customization only; no business, backend, token, Room, OCR, duplicate, CSV, or upload flow changed.

## Background Gallery Visuals - 2026-05-07

Real-device check artifact:

- `artifacts/background_gallery_theme_visuals.png`
- copied to `artifacts/background_gallery.png`

Observed result:

- Built-in background cards now use the preferred skin's `ThemeVisuals` for card tint, selected/recommended markers, border, shadow, hero strip, glass strip, and glow.
- The gallery previews read as miniature App surfaces rather than plain gradient swatches, while still keeping the built-in background gradient visible.
- Category chips use the shared `AppFilterChip` and a horizontally scrollable row, preventing the `插画` label from wrapping vertically on the real device.
- The custom actions use shared App buttons, so `从相册选择` and `主题默认` match the rest of the visual system.
- The background and theme flow remains local UI customization only; no business, backend, token, Room, OCR, duplicate, CSV, or upload flow changed.

## Background Preview Visuals - 2026-05-07

Real-device check artifacts:

- `artifacts/background_preview_theme_visuals.png`
- copied to `artifacts/background_preview.png`
- `artifacts/background_preview_actions_final.png`

Observed result:

- Preview cards now use the selected skin's `ThemeVisuals` for glass/solid content layers, border, shadow, and readable card hierarchy.
- Pending and Stats preview roles retain more atmosphere, while Ledger and Edit preview roles use more solid surfaces for scan and form readability.
- The preview's `确认入账` sample and final `应用背景` action use shared App primary buttons, keeping the apply step visually consistent with the rest of the app.
- The final action area remains visible above the floating bottom navigation after scrolling; cancel remains a secondary action and does not overpower apply.
- The background preview flow still saves nothing until `应用背景` is tapped; no business, backend, token, Room, OCR, duplicate, CSV, or upload flow changed.

## Page Scaffold Recheck - 2026-05-07

Real-device check artifacts:

- `artifacts/pending_scaffold_after.png`
- `artifacts/ledger_scaffold_after.png`
- `artifacts/stats_scaffold_after.png`
- `artifacts/settings_scaffold_after.png`

Observed result:

- The design reference thumbnails in `docs/design_reference/thumbnails/` were opened and compared against the current real-device screenshots before making this pass.
- The main shell no longer applies extra Material Scaffold system-bar padding on top of the page scaffold. `AppPageScaffold` is now the owner of status-bar and bottom-bar spacing.
- Pending, Ledger, Stats, and Settings all start closer to the status bar without title clipping, reducing the "content pushed down" effect seen in the previous screenshots.
- Compact pages now use tighter top padding, while comfortable pages retain a small amount of breathing room.
- The floating bottom navigation remains independent of content layout. Scrollable screens keep bottom-bar-aware padding through the shared page scaffold.
- This pass only changed global layout rhythm and the scaffold spacing test. It did not change business logic, ViewModel, Repository, backend API, Room, OCR, duplicate, CSV, upload, or token flow.

## Ledger Density Polish - 2026-05-07

Real-device check artifact:

- `artifacts/ledger_density_polish_final.png`

Observed result:

- Ledger keeps the same month, category, search, sync, export, and manual-entry behavior, but the screen now exposes more bills in the first viewport.
- The ledger title is less oversized, matching the design reference's reading-first posture more closely.
- The summary strip, filter panel, and bill rows were lightly compressed without sacrificing amount, merchant, date, or category readability.
- A too-small search field attempt was rejected during the real-device pass because it clipped placeholder text; the final screenshot uses a readable search height.
- No backend API, ViewModel, Repository, Room, OCR, duplicate, CSV, upload, token, or persistence behavior changed.

## Stats Density Polish - 2026-05-07

Real-device check artifact:

- `artifacts/stats_density_polish_final.png`

Observed result:

- Stats keeps the same month selection, refresh, category insight, trend, lifestyle, and merchant data flow, but the overview hero no longer consumes most of the first viewport.
- Month comparison and budget context were reduced from two embedded mini cards to one light hero status line, keeping the information without turning the hero into a report panel.
- The recent 7-day trend chart is shorter and still readable, so the classification insight begins in the first viewport.
- The floating bottom navigation remains unchanged; scrollable content keeps bottom-bar-aware padding so lower stats cards can scroll fully above the navigation.
- No backend API, ViewModel, Repository, Room, OCR, duplicate, CSV, upload, token, or persistence behavior changed.

## Expense Edit Density Polish - 2026-05-07

Real-device check artifacts:

- `artifacts/expense_edit_density_polish_final.png`
- `artifacts/expense_edit_density_polish_final_loaded.png`

Observed result:

- Expense Edit now uses the shared header without the global `小票夹` eyebrow, making the confirmation task feel more like a focused edit flow instead of another overview page.
- The OCR draft preview card is smaller and still keeps merchant, amount, category, confidence, screenshot preview, original-image action, and OCR retry visible.
- Form spacing was tightened so amount, merchant, category, category chips, note, and consume-time controls appear earlier without changing validation or submit behavior.
- The final loaded screenshot confirms protected screenshot preview still renders after the compact pass; loading fallback remains available while the image request is in flight.
- No backend API, ViewModel, Repository, Room, OCR, duplicate, CSV, upload, token, confirm, reject, or save behavior changed.

## Pending Benchmark Density Polish - 2026-05-07

Real-device check artifact:

- `artifacts/pending_benchmark_density_final.png`

Observed result:

- Pending remains the benchmark page and still keeps upload as the primary CTA, but the hero card is slightly shorter and less oversized than the previous screenshot.
- The pending and suspected-duplicate glass metrics were tightened so the first bill card begins higher in the first viewport.
- The page still preserves the product boundary copy: screenshots and recognition drafts do not auto-enter the ledger.
- The floating bottom navigation remains unchanged; pending bill cards keep bottom-bar-aware scroll padding.
- No backend API, ViewModel, Repository, Room, OCR, duplicate, CSV, upload, token, confirm, reject, or persistence behavior changed.

## Ledger Tools Sheet Polish - 2026-05-07

Real-device check artifacts:

- `artifacts/ledger_tools_main.png`
- `artifacts/ledger_tools_sheet.png`

Observed result:

- Ledger now keeps the main page focused on the month, current filter summary, total amount, and bill list.
- Category chips, note search, CSV export, and manual sync moved into a bottom tools sheet opened from `筛选`.
- The main filter panel no longer exposes every control at once, reducing first-viewport crowding while keeping all existing actions reachable.
- The tools sheet was captured on the attached Xiaomi 15 Pro; it stays below the status bar and does not overlap the page title.
- This was a Ledger-only information-hierarchy pass. It did not change backend API, ViewModel, Repository, Room, OCR, duplicate, CSV, upload, token, confirm, reject, or persistence behavior.

## Pending Tools Sheet Polish - 2026-05-07

Real-device check artifacts:

- `artifacts/pending_tools_loaded.png`
- `artifacts/pending_tools_sheet.png`

Observed result:

- Pending keeps upload, pending count, duplicate reminder count, and the bill list on the main page.
- Display density and refresh moved into a `待处理设置` bottom sheet opened from the compact/comfortable pill.
- The main page no longer shows both density chips and refresh as always-visible controls above the first bill.
- A UTF-8/mojibake scan was run over Android source and Markdown docs after this pass; no suspicious mojibake markers were found.
- This was a Pending-only information-hierarchy pass. It did not change backend API, ViewModel, Repository, Room, OCR, duplicate, CSV, upload, token, confirm, reject, or persistence behavior.

## Page Scaffold Rule Re-lock - 2026-05-07

Real-device check artifact:

- `artifacts/pending_scaffold_after.png`

Observed result:

- Shared page scaffold spacing was returned to the documented gate values: compact pages start at 16dp after the status inset, comfortable pages start at 24dp.
- The floating bottom bar height is again represented by the named `AppPageDefaults.BottomBarHeight = 72.dp` constant instead of a screenshot-specific larger value.
- Settings secondary pages no longer apply an extra top reduction outside the shared scaffold.
- Expense Edit no longer overrides the shared horizontal page padding.
- The attached-device Pending screenshot confirms the title and primary content sit below the system status bar instead of overlapping time, VPN, 5G, or battery indicators.
- This was a page-scaffold-only correction. It did not change card styling, button styling, theme visuals, backend API, ViewModel, Repository, Room, OCR, duplicate, CSV, upload, token, confirm, reject, or persistence behavior.

## Stats Theme Fit Polish - 2026-05-07

Real-device check artifacts:

- `artifacts/stats_theme_fit_final.png`
- `artifacts/stats_theme_fit_compact.png`

Observed result:

- The floating bottom navigation selected capsule now uses `ThemeVisuals.primary`, so Pine, Harbor, Pomelo, Berry, and Night follow their theme package primary color instead of a fixed blue-green.
- The selected capsule height and shadow were reduced to make the bottom bar less visually protrusive while keeping the current tab readable.
- The category insight card now uses `ThemeVisuals.solidCard` and its metric pills use `ThemeVisuals.chipSelected`, improving readability and matching the theme package surface language.
- The recent trend card and category insight card were lightly compressed so the category insight can be read above the floating bottom bar on the attached Xiaomi 15 Pro.
- This was a shared visual-system polish. It did not change backend API, ViewModel, Repository, Room, OCR, duplicate, CSV, upload, token, confirm, reject, or persistence behavior.
