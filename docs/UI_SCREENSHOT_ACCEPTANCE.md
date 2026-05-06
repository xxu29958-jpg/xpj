# UI Screenshot Acceptance

Date: 2026-05-06

Device: Xiaomi 15 Pro, real device over ADB

Variant: `grayDebug`

Scope: design-system / page-scaffold / visual polish acceptance. This document records real-device screenshots captured after the current Android UI pass. Large screenshots stay under `artifacts/` and are not committed.

## Verified Screenshots

| Target | Artifact | Status | Notes |
| --- | --- | --- | --- |
| Pending empty | `artifacts/pending_empty.png` | Captured | Pending benchmark empty state with hero, upload CTA, upload flow, and empty card. |
| Pending offline | `artifacts/pending_offline.png` | Captured | Shows network fallback as a light product state; title is not covered by loading. |
| Ledger with items | `artifacts/ledger_items.png` | Captured | Ledger remains readable with compact filter area and visible list. |
| Ledger search empty | `artifacts/ledger_search_empty.png` | Captured | Search empty state captured with a nonsense query. |
| Stats empty | `artifacts/stats_empty.png` and `artifacts/stats_current.png` | Captured | Empty state includes lightweight skeleton placeholders and primary refresh CTA. |
| Settings root | `artifacts/settings_root.png` | Captured | Settings uses secondary-page entry structure and unified entry card styling. |
| Appearance | `artifacts/appearance.png` | Captured | Theme grid and appearance structure captured. |
| Background gallery | `artifacts/background_gallery.png` | Captured | Built-in background catalog and categories captured. |
| Background preview | `artifacts/background_preview.png` | Captured | Preview confirms page-effect preview before applying. |
| Expense edit | `artifacts/expense_edit.png` | Captured | Edit screen remains compact and readable. |

## Not Captured In This Run

| Target | Reason | Required Follow-Up |
| --- | --- | --- |
| Pending with items | Current device state has `0` pending bills. Do not fabricate pending data just for a visual screenshot. | Capture after iPhone or Android uploads a real screenshot and before confirmation. |
| Stats with data | Current stats response/page state is empty on the real device. Ledger data exists locally, but this acceptance pass did not change stats data flow. | Capture after the backend monthly stats endpoint returns confirmed monthly data, or after a later business pass explicitly adds offline stats fallback. |

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
- Pending remains the benchmark page; the current screenshot is suitable for human review.
- Ledger and Expense Edit are kept more solid and compact than Pending/Stats, preserving readability over immersion.
- Background and theme flows are captured as local UI customization only; no background image is uploaded to the backend.
- No backend API, repository, Room, OCR, duplicate, CSV, upload, or token flow was changed during this acceptance pass.
