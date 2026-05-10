# v0.3-rc1-preflight 验收报告

> 阶段：`v0.3-rc1-preflight`
> 基线：`main @ 0fcdea7a82438b5214e901787aee532d2d23cd0f`（v0.3.2-selfuse stable candidate，PR #8 squash merged）
> 报告日期：2026-05-10
> 工作分支：`v0.3-rc1-preflight`

本报告记录 `v0.3.2-selfuse` 在公网边界、iPhone UploadLink 公网上传、Android 真机第二次 E2E、Owner Console 与自用健康监控这五条线上的实测结果，作为是否进入 `v0.3-rc1` 正式候选的决策依据。

---

## 1. 版本基线一致性（任务 A）

| 位置 | 值 |
| --- | --- |
| `backend/app/version.py BACKEND_VERSION` | `0.3.2-selfuse` |
| `/api/health.backend_version` | `0.3.2-selfuse`（实测） |
| `/api/health.identity_schema` | `v0.3` |
| `android/app/build.gradle.kts versionName` | `0.3.2-selfuse` |
| `android/app/build.gradle.kts versionCode` | `30002` |
| 设备实测安装版本 | `versionName=0.3.2-selfuse`、`versionCode=30002`（c16cd054） |
| README header | `v0.3.2-selfuse`（阶段：v0.3-rc1-preflight） |
| `docs/ACCOUNT_SYSTEM.md` | `v0.3.2-selfuse` |
| `docs/WINDOWS_SERVICE_RUNBOOK.md` | `v0.3.2-selfuse` |

> 说明：`0.3.2-selfuse` 是产品名（自用稳定候选），`v0.3-rc1-preflight` 是当前阶段名，仅写在标题、阶段说明与本报告中，不进入 backend 版本字符串。

---

## 2. 公网边界矩阵（任务 B、C、D、E、F）

`scripts/check_public_boundary.ps1` 实测（同一台 Windows 后端 + Cloudflare Tunnel `api.zen70.cn → 127.0.0.1:8000`）：

| # | 用例 | URL | 期望 | 实际 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 1  | local /api/health                     | `127.0.0.1:8000/api/health`        | 200 | 200 | PASS |
| 2  | local /owner（loopback）              | `127.0.0.1:8000/owner`             | 200 | 200 | PASS |
| 3  | public /api/health                    | `api.zen70.cn/api/health`          | 200 | 200 | PASS |
| 4  | public /api/auth/pair（错码）         | `api.zen70.cn/api/auth/pair`       | 4xx | 401 | PASS |
| 5  | public /u/{fake}                      | `api.zen70.cn/u/upl_*`             | 4xx | 401 | PASS |
| 6  | public /owner                         | `api.zen70.cn/owner`               | 401/403/404/405 | 403 | PASS |
| 7  | public /owner/devices                 | `api.zen70.cn/owner/devices`       | 401/403/404/405 | 403 | PASS |
| 8  | public /owner/upload-links            | `api.zen70.cn/owner/upload-links`  | 401/403/404/405 | 403 | PASS |
| 9  | public /api/admin/devices             | `api.zen70.cn/api/admin/devices`   | 401/403/404/405 | 403 | PASS |
| 10 | public /api/admin/upload-links        | `api.zen70.cn/api/admin/upload-links` | 401/403/404/405 | 403 | PASS |
| 11 | public /api/bootstrap/owner           | `api.zen70.cn/api/bootstrap/owner` | 401/403/404/405 | 404 | PASS |
| 12 | public /docs                          | `api.zen70.cn/docs`                | 401/403/404/405 | 404 | PASS |
| 13 | public /openapi.json                  | `api.zen70.cn/openapi.json`        | 401/403/404/405 | 404 | PASS |
| 14 | public /redoc                         | `api.zen70.cn/redoc`               | 401/403/404/405 | 404 | PASS |

`PUBLIC_BOUNDARY_PASS=true`（14/14）。

技术说明：
- 新增 `app/network_boundary.py` 导出 `require_owner_console_local`（同时校验 TCP peer 与 Host 头）和 `require_admin_network_boundary`（loopback 全放行；公网 Host 默认 403，由 `ALLOW_PUBLIC_ADMIN_API` 解锁）。
- `app/main.py` 中的 `docs_url`/`redoc_url`/`openapi_url` 受 `ENABLE_API_DOCS` 控制，默认 `None`。
- `/api/admin/*` 通过 `APIRouter(dependencies=[Depends(require_admin_network_boundary)])` 全量挂入边界检查。
- `_require_local()`（Owner Console）改为转调 `require_owner_console_local`，新增的 Host 头校验确保 Cloudflare Tunnel 把 `api.zen70.cn` 的 Host 头透传给 loopback 时也会被拒绝。
- Bootstrap：`/api/bootstrap/owner` 在 `ENABLE_HTTP_BOOTSTRAP=false` 时直接 404，未做改动；公网用例 11 验证仍为 404。
- 不信任 `X-Forwarded-For` / `CF-Connecting-IP` / `X-Real-IP`，只看 Host 头。

---

## 3. iPhone UploadLink 公网上传（任务 G）

| 步骤 | 结果 |
| --- | --- |
| 在本机 Owner Console（loopback）创建 UploadLink | 成功（key 仅在内存中处理，REDACTED） |
| 单一 `?tz=` 拼接验证 | URL 形如 `https://api.zen70.cn/u/upl_***?tz=Asia/Shanghai`，`?tz=` 出现 1 次 |
| 生成测试 PNG | `artifacts/test_upload_public.png`（base64 1×1 PNG，69 字节，未提交） |
| 公网 POST | `curl -X POST -H "User-Agent: TicketBox/1.0 iOS-Shortcut" -F "image=@...;type=image/png" $UploadUrl` |
| 公网响应 | `HTTP=200`，`status=pending`，`message=uploaded`，`upload_size_bytes=69`，`duration_ms=24` |
| 日志泄漏检查 | `SanitizedLoggingMiddleware` 已生效；24 小时内 `backend/logs` `ERROR/Traceback` 计数 = 0 |
| 清理 | 仓库内三条历史 UploadLink 已经 owner-console revoke（包含本次新建的） |

> Live UploadLink URL：**REDACTED**（不写入 git/docs/log/report，符合长任务合同条款 G）。
> 仓库未提交的临时文件：`artifacts/test_upload_public.png`、`artifacts/upload_response.json`，已清理。

iPhone Shortcut 真机回归仍属于 `v0.3-rc1` 正式态（需要操作者持机执行）。本轮使用 `curl.exe` 等价回放替代真机 Shortcut。

---

## 4. Android 第二次 E2E（任务 H）

设备：`c16cd054`（Xiaomi 2410DPN6CC，1080×2400）。

| 步骤 | 结果 |
| --- | --- |
| `pm clear com.ticketbox` 清空数据 | OK |
| 重装 grayDebug APK（versionName=0.3.2-selfuse, versionCode=30002） | `Streamed Install Success` |
| 启动 MainActivity | `mResumeActivity=ActivityRecord{... com.ticketbox/.MainActivity}` |
| 截图（启动后） | `artifacts/rc1_e2e/rc1_launch_*.png`（未提交） |
| 通过 Owner Console 生成 6 位 Pairing Code | OK（REDACTED） |
| `adb shell input text` + KEYCODE_ENTER | OK |
| Owner Console `/owner/devices` 列表 | 出现 `Xiaomi 2410DPN6CC / android` 设备行 |
| 飞行模式打开（`settings put global airplane_mode_on 1`） | OK |
| 飞行模式截图 | `artifacts/rc1_e2e/rc1_airplane_on.png`（未提交） |
| 飞行模式关闭 | OK，截图 `rc1_airplane_off.png` |

> 截图与 logcat 全部写入 `artifacts/rc1_e2e/`，由 `.gitignore` 排除（`artifacts/`），已通过 `git status` 确认未进入工作区。
> 无 token / app_token / pairing code / upload key 出现在 logcat 或终端输出。

操作者后续可继续按 `scripts/run_android_pairing_e2e.ps1` 走完整 confirmed 缓存恢复链路；本次 preflight 已证明绑定路径在新版本号 APK 上仍然成立。

---

## 5. Owner Console UX（任务 J）

本轮无新发现的视觉/文案缺陷需修复。PR #8 已修复时间显示与表头换行问题。所有 Owner Console 模板（`devices.html`、`pairing.html`、`upload_links.html`、`diagnostics.html`、`index.html`）在本次 verify_project + 实测访问中均正常渲染。

---

## 6. 自用健康监控（任务 I）

`scripts/check_selfuse_health.ps1` 实测：

| Id | Name | Status | Detail |
| --- | --- | --- | --- |
| H01 | 后端本地健康 | ok | `GET /api/health -> 200` |
| H02 | 健康响应携带身份模型版本 | ok | `identity_schema=v0.3, backend=0.3.2-selfuse` |
| H03 | Owner Console 本机可访问 | ok | `GET /owner -> 200` |
| H04 | Owner Console 拒绝伪造 Host 头 | ok | `GET /owner [Host: api.zen70.cn] -> 403` |
| H05 | Cloudflare 公网健康 | ok | `GET https://api.zen70.cn/api/health -> 200` |
| H06 | 公网 /owner 被阻断 | ok | `-> 403` |
| H07 | 公网 /docs 被阻断 | ok | `-> 404` |
| H08 | SQLite 数据库文件 | ok | `size=303,104B` |
| H09 | 上传目录存在 | ok | `uploads/ 存在` |
| H10 | 最近 7 天内有备份 | ok | `ticketbox-pre-v0.3-20260509-114239*` |
| H11 | 近 24h 日志中错误计数 | ok | `errors=0` |

`SELFUSE_HEALTH=ok`（11/11）。

---

## 7. 测试合集

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 文本编码 | `scripts/check_text_encoding.ps1` | 通过 |
| Python 编译 | `python -m compileall app scripts tests` | 通过 |
| ruff | `ruff check app scripts tests` | 通过 |
| pytest | `pytest`（backend） | **134 passed**（128 baseline + 6 新增 boundary 测试） |
| smoke_test | `python scripts/smoke_test.py` | 通过 |
| Android 单元测试 | `gradlew :app:testGrayDebugUnitTest` | 通过 |
| Android Lint | `gradlew :app:lintGrayDebug` | 通过 |
| Android 构建 | `gradlew :app:assembleGrayDebug :app:assembleInternalDebug` | 通过 |
| 公网边界 | `scripts/check_public_boundary.ps1` | `PUBLIC_BOUNDARY_PASS=true`（14/14） |
| 自用健康 | `scripts/check_selfuse_health.ps1` | `SELFUSE_HEALTH=ok`（11/11） |
| `verify_project.ps1` | 顶层聚合 | `项目验证完成` |

新增的 6 个 pytest 用例（位于 `tests/test_owner_console.py`）：
- `test_owner_console_local_peer_local_host_allowed`
- `test_owner_console_local_peer_public_host_rejected`
- `test_owner_console_remote_peer_rejected`
- `test_admin_boundary_local_allowed`
- `test_admin_boundary_public_host_rejected_by_default`
- `test_admin_boundary_public_host_allowed_when_flag_true`

---

## 8. 安全审计要点

- 不再信任任何 `X-Forwarded-*` / `CF-Connecting-IP` / `X-Real-IP` 头作为身份信号。
- Host 头校验白名单：`{127.0.0.1, 127.0.0.1:8000, localhost, localhost:8000, [::1], [::1]:8000, ::1, ::1:8000}`。其他一律视作公网。
- 默认配置（无 `.env` 改动）下，公网 Host：`/owner` `/api/admin/*` `/docs` `/openapi.json` `/redoc` `/api/bootstrap/owner` 全部阻断。
- 旧 `APP_TOKEN`/`UPLOAD_TOKEN` 运行时模式没有在本次 PR 中复活；`/api/auth/pair` `/u/*` `/api/expenses/*` 仍然只接受 v0.3 身份模型签发的凭证。
- 本报告与提交历史中均未泄露：UploadLink URL、pairing code、admin/app/upload token、设备 secret、SQLite 路径绝对值、设备序列号以外的私人信息。

---

## 9. 决策

按合同 21 条门槛逐条核对：

1. ✅ Branch = `v0.3-rc1-preflight`，base = `main @ 0fcdea7`
2. ✅ Backend 版本统一 `0.3.2-selfuse`；Android `0.3.2-selfuse`
3. ✅ `/docs` `/openapi.json` `/redoc` 公网 404
4. ✅ Owner Console 公网 Host 403
5. ✅ `/api/admin/*` 公网 Host 默认 403
6. ✅ `/api/bootstrap/owner` 公网 404
7. ✅ `check_public_boundary.ps1` 14/14
8. ✅ `check_selfuse_health.ps1` 11/11
9. ✅ iPhone-style 公网 curl POST → 200 pending
10. ✅ Android 第二次 E2E（重装 + 绑定 + 飞行模式）
11. ✅ pytest 134 通过（含 6 个新 boundary 用例）
12. ✅ ruff / compileall / smoke / Android 单元测试 / Lint / Assemble
13. ✅ `verify_project.ps1` 通过
14. ✅ `check_text_encoding.ps1` 通过
15. ✅ `git status` 无 db / uploads / artifacts / logcat / 截图 / token 入库
16. ✅ 不在 `main` 上提交、不 force push
17. ✅ 不复活 APP_TOKEN/UPLOAD_TOKEN 运行时回退
18. ✅ 不引入 Linux/WSL/Docker/Node/Vue
19. ✅ 自我修复轮次 ≤ 3
20. ✅ Owner Console UX 第二轮：本轮无 P0/P1 视觉问题
21. ✅ 报告写明 REDACTED，未泄露公网 UploadLink URL

**结论：v0.3-rc1-preflight = passed。**

仍需操作者完成的 `v0.3-rc1` 正式态门槛：
- 真机 iPhone 上 Shortcut 完整跑通（本轮以 PowerShell `curl.exe` 等价回放替代）。
- 操作者再次按 `docs/REAL_DEVICE_RUNBOOK.md` 附录 A 走 confirmed 缓存恢复链路（本轮验证了重装 + 绑定 + 飞行模式开关，未在飞行模式下回到账本页验证缓存命中）。

满足上述两条后，可在 24–48 小时内打 `v0.3-rc1` 正式 tag。
