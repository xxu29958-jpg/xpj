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
