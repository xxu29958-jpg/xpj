# Gray Release Status - 2026-05-07

Branch: `codex/gray-release-tenant-ux`

Status: automated gray acceptance passed again after hardening the public preflight upload check. Remaining items are manual real-device checks with real user screenshots and cellular network.

## Service Status

Verified on 2026-05-07:

- Local backend health: `http://127.0.0.1:8000/api/health` passed.
- Public backend health: `https://api.zen70.cn/api/health` passed.
- Public app auth check: `https://api.zen70.cn/api/auth/check` passed.
- Cloudflare Tunnel path is reachable from the public domain.
- Backend listens on `127.0.0.1:8000`.

The backend process is started from `backend\.venv\Scripts\python.exe`. On this Windows host the venv launcher delegates to the bundled base Python executable, so diagnostics may show a child Python process with the same uvicorn command line.

## Verification Passed

`scripts\verify_project.ps1` completed successfully:

- Backend compile check passed.
- Ruff passed.
- Pytest passed: 38 tests.
- Backend smoke test passed.
- Android `:app:testGrayDebugUnitTest` passed.
- Android `:app:assembleGrayDebug` passed.
- Android `:app:assembleInternalDebug` passed.
- Android `:app:lintGrayDebug` passed.

Backend smoke coverage includes health, auth, upload validation, raw upload, multipart upload, pending, protected image, thumbnail, confirm, reject, OCR retry, duplicate handling, CSV export, rules, and monthly stats.

## Public Endpoint Preflight

Fixed and re-ran:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_cloudflare_endpoint.ps1 -ServerUrl https://api.zen70.cn
```

Result:

- Health passed.
- Auth passed.
- OpenAPI contract route checks passed.
- Test screenshot upload created a pending expense.
- The pending expense was found in `/api/expenses/pending`.
- The test pending was automatically cleaned via `/api/expenses/{id}/reject`.

Script hardening added:

- Flatten pending API results before searching.
- Normalize scalar values such as `id` and `public_id`.
- Find the uploaded expense by id instead of relying on PowerShell array behavior.
- Always reject the test upload in `finally` when an id was created.

## Gray Acceptance

Ran:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\accept_gray_release.ps1 -SkipProjectVerify -UseTemporaryKeystore -Serial c16cd054 -Adb E:\projects\xiaopiaojia\.toolchains\android-sdk\platform-tools\adb.exe
```

Result:

- Text encoding check passed.
- Local and public API checks passed.
- Public iPhone shortcut upload endpoint created a pending test expense.
- Public Android app upload endpoint created a pending test expense.
- Both test pending expenses were cleaned via reject.
- Windows diagnosis passed.
- Temporary local release keystore was generated for acceptance only.
- Gray release APK was generated.
- Gray debug APK was installed and launched on the attached device.

Generated release APK:

```text
E:\projects\xiaopiaojia\android\app\build\outputs\apk\gray\release\app-gray-release.apk
```

APK size in this run:

```text
54,332,353 bytes
```

## Important Notes

- The temporary acceptance keystore is not a production signing key.
- Production gray release still needs the real keystore environment variables before sending to testers.
- Some nested PowerShell output can render mojibake in the terminal, but the repository files are UTF-8 and the acceptance script's encoding check passed.

## Manual Checks Still Required

These require real interaction and should not be marked complete by automation:

1. iPhone Shortcut uploads a real bill screenshot to `https://api.zen70.cn/api/upload-screenshot`.
2. Android pending list shows that real uploaded bill.
3. Android photo picker upload creates a pending bill through `/api/app/upload-screenshot`.
4. User edits amount, merchant, category, note, and expense time.
5. Confirming the bill removes it from pending and writes confirmed cache.
6. Ledger shows the confirmed bill.
7. Stats changes after the confirmed bill is included.
8. Cellular network can reach `https://api.zen70.cn` away from the local LAN.
9. Clean tester device installs the production-signed gray APK.

## Product Boundaries Rechecked

- Upload creates `pending`, not `confirmed`.
- OCR retry only updates draft fields.
- Duplicate detection only warns.
- Reject marks the expense as rejected.
- Confirmed expenses drive ledger and stats.
- Background images remain local to Android and are not uploaded.
