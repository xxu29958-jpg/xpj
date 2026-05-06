# Gray Release Status - 2026-05-06

Branch: `codex/gray-release-tenant-ux`

Pull request: https://github.com/zhe9898/7/pull/2

Status: automated gray-release validation is complete; remaining items are real-world manual checks that require fresh bill screenshots, the iPhone shortcut, Android photo picker interaction, or cellular network verification.

## Completed Automatically

### Code And CI

- Local worktree is clean.
- Branch is pushed to `origin/codex/gray-release-tenant-ux`.
- GitHub CI is green:
  - Backend: pass
  - Android: pass
- PR is mergeable.

### Backend Verification

Run through `scripts\verify_project.ps1`:

- Python compile check: passed.
- Ruff: passed.
- Pytest: 38 passed.
- Backend smoke test: passed.

Smoke test coverage includes:

- Health check.
- Auth check.
- Invalid token error.
- Upload token check.
- Unsupported file type.
- Image header validation.
- File too large.
- Raw image upload.
- Multipart screenshot upload.
- Pending query.
- Manual expense create.
- Protected image and thumbnail.
- Amount required on confirm.
- Patch expense.
- OCR retry.
- Recognize text.
- Confirm expense.
- Confirmed pagination.
- Categories and months.
- CSV export.
- Monthly stats.
- Category rules CRUD.
- Duplicate detection.
- Mark not duplicate.
- Lifestyle stats.
- Reject expense.

### Android Verification

Run through `scripts\verify_project.ps1` and direct Gradle commands:

- `:app:testGrayDebugUnitTest`: passed.
- `:app:assembleGrayDebug`: passed.
- `:app:assembleInternalDebug`: passed.
- `:app:lintGrayDebug`: passed.

### Gray Release Acceptance

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\accept_gray_release.ps1 -SkipProjectVerify -UseTemporaryKeystore -Serial c16cd054 -Adb E:\projects\xiaopiaojia\.toolchains\android-sdk\platform-tools\adb.exe
```

Result:

- Public OpenAPI route checks passed.
- Public iOS upload endpoint created a pending test expense.
- Public Android app upload endpoint created a pending test expense.
- Both test expenses were cleaned via `reject`.
- Windows diagnosis checks passed.
- Temporary local release keystore was generated for acceptance only.
- Gray release APK was generated.
- Latest gray debug APK was installed and launched on the attached device.

Generated APK:

```text
android/app/build/outputs/apk/gray/release/app-gray-release.apk
```

## UI Screenshot Acceptance

Recorded in:

```text
docs/UI_SCREENSHOT_ACCEPTANCE.md
```

Captured real-device screenshots under `artifacts/`:

- `pending_empty.png`
- `pending_with_items.png`
- `pending_offline.png`
- `ledger_items.png`
- `ledger_search_empty.png`
- `stats_empty.png`
- `stats_with_data.png`
- `settings_root.png`
- `appearance.png`
- `background_gallery.png`
- `background_preview.png`
- `expense_edit.png`

Current screenshot notes:

- `pending_with_items.png` now uses the current real-device state with 3 pending expenses.
- `stats_with_data.png` was captured after refreshing the stats page and shows the real monthly total.
- A Xiaomi floating system control appears in some screenshots; it is not App UI and should be disabled before clean marketing captures.

## Manual Checks Still Required

These are intentionally left as manual because they depend on real devices, real screenshots, or network conditions:

- iPhone shortcut uploads a real bill screenshot to `https://api.zen70.cn/api/upload-screenshot`.
- Android pending list shows that real pending expense. Current device already has pending expenses visible.
- Android user edits amount, merchant, category, note, and expense time.
- Confirming the bill moves it from pending to confirmed.
- Ledger shows the confirmed bill.
- Stats changes after the confirmed bill is included by the backend stats endpoint. Current device stats can show real data after refresh.
- Android photo picker upload creates a pending expense.
- Cellular network access works away from the local Wi-Fi / PC LAN.
- Release APK is signed with the production gray keystore, not the temporary local acceptance keystore.
- Release APK is installed on a clean tester device.

## Product Boundaries Confirmed

- Upload creates `pending`, not `confirmed`.
- OCR retry only updates draft fields.
- Duplicate detection only warns.
- Reject marks the expense as rejected.
- Confirmed expenses are the source for ledger and stats.
- Background customization stays local to Android and is not uploaded to the backend.

## Next Recommended Move

Do not continue broad UI changes before a fresh manual review of the current screenshots.

Next concrete sequence:

1. Install the current gray build on the test device.
2. Upload a real iPhone bill screenshot.
3. Capture a clean `pending_with_items.png` with the Xiaomi floating control hidden if needed.
4. Edit and confirm the bill on Android.
5. Capture a clean `stats_with_data.png`.
6. If the real-device screenshots pass review, merge PR #2.
