# v0.3.3 产品化总结（productization）

> 基线：`v0.3.2-selfuse` + `v0.3-rc1-preflight`（PR #9 已合并到 main，`698dde21`）。
> 目标：把小票夹从 "工程可用" 推到 "自用稳定产品化"。无后端 schema 变更，无大型前端框架，无自动合并。

## 1. 版本号

- 后端 `BACKEND_VERSION` = `0.3.3`（`backend/app/version.py`）
- Android `versionCode` = `30003`，`versionName` = `0.3.3`（`android/app/build.gradle.kts`）

## 2. Release APK 通道

`scripts/build_release_apk.ps1` 增加 `-Variant {release|debug}` 参数：

- `release`（默认）：要求 keystore 环境变量；产出 `app-gray-release.apk`。
- `debug`：跳过 keystore 检查；产出 `app-gray-debug.apk`，用于自用 / 灰度安装。

输出路径与 `release.json` 清单中的 `build_type` 字段会随 `Variant` 自动切换；产物 / keystore / `.apk` 仍由 `.gitignore` 拦截，不入库。

## 3. Windows 计划任务

新增本机维护脚本（PowerShell，UTF-8 BOM）：

- `scripts/restart_backend.ps1`：先调 `stop_backend.ps1`，再调 `start_backend.ps1`，等价于 "重启后端 8000 端口"。
- `scripts/check_windows_task_status.ps1`：用 `Get-ScheduledTask` + `Get-ScheduledTaskInfo` 输出 `TicketboxBackend` / `TicketboxCloudflareTunnel` / `TicketboxBackup` 三个任务的状态、上次运行时间、上次结果码。

不创建新计划任务，不改 service 注册逻辑，避免与已落地的运行时配置冲突。

## 4. 备份可见化

- 新增 `backend/app/services/backup_service.py`：
  - `BackupEntry(file_name, size_bytes, created_at, kind)` frozen dataclass。
  - `list_backups()` 按 mtime 倒序返回 `backend/backups/` 下的 `.db` 文件。
  - `latest_backup()` 取最新一份。
  - `create_manual_backup()` 把当前 SQLite 文件复制为 `ticketbox-manual-{stamp}.db`，重名时追加计数后缀。
- 新增 `/owner/backups`（GET 列表 + POST 触发手动备份），仅本机访问；新增 Owner Console 导航条目 "💾 数据库备份"；首页快捷入口同步指向。
- 新增测试 `backend/tests/test_owner_console_backups.py`（5 项，含远程 403、手动备份成功创建、不泄漏绝对路径）。

## 5. 错误中文化

`backend/app/errors.py` 全量重写 `ERROR_MESSAGES`：所有键值改为面向自用人的口语式中文（如 "登录已失效，请重新绑定设备。"、"图片不存在或已被清理。"、"请先填写金额。"），并新增 `admin_api_local_only`。`backend/app/network_boundary.py` 的管理接口拒绝路径改为统一用 `AppError("admin_api_local_only", status_code=403)`，不再写死中文。两个原本依赖旧文案的测试同步更新。

## 6. iPhone Shortcut 排障

`backend/app/templates/owner/upload_links.html` 底部新增排障卡片（橙色侧边条），列出 6 步常见问题：链接过期、未带 `?tz=` 查询参数、`Content-Type` 不是 `image/png` / `image/jpeg`、HEIC 转 JPEG、TLS 时间漂移、Cloudflare 隧道未连。卡片只是静态说明，不引入新依赖。

## 7. /web 网页版账本（MVP）

新增 `backend/app/routes/web_app.py`（router prefix `/web`，仅本机访问），覆盖：

- `/web` → 重定向到 `/web/pending`
- `/web/pending`（待确认列表）
- `/web/confirmed?page&month`（已确认账单 + 月份过滤）
- `/web/stats`（月度统计）
- `/web/edit/{id}` GET + `/web/save/{id}` POST（编辑：`amount_yuan` / `merchant` / `category` / `note`）
- `/web/confirm/{id}` POST、`/web/reject/{id}` POST
- `/web/image/{id}` / `/web/thumb/{id}`（透传 expense_service 的图片返回）

模板存放 `backend/app/templates/web/`，样式只用一份 `backend/app/static/web/web.css`（无框架；sticky 顶栏、`.card`、`.btn-*`、`.stat-grid`、`.form-row`、`.pagination`、`.receipt-img`、`.thumb`）。Owner Console 首页新增 "🖥️ 网页版账本" 入口（`target=_blank` 到 `/web`）。

新增测试 `backend/tests/test_web_app.py`（10 项，含远程 403、本机 200、保存修改金额、错误金额提示中文、缺金额无法确认、不泄漏 `token_hash`）。

## 8. Android UX

- 仅做版本号同步，不动既有页面 / 主题 / 状态机，避免影响已稳定的灰度通道。
- `assembleGrayDebug` / `lintGrayDebug` / `testGrayDebugUnitTest` 全部 `BUILD SUCCESSFUL`（由 `scripts/verify_project.ps1` 串起来跑过）。

## 9. Owner Console UX

- 顶部导航新增 "备份" 链接。
- 首页 "快捷入口" 加入 "💾 数据库备份" 与 "🖥️ 网页版账本" 两个卡片。
- 不重排现有信息密度，不改 CSS 主题色。

## 10. 测试 / 验证

- `pytest`：148 collected，**148 passed**，约 2 分钟。
- `ruff check app tests` / `ruff check app scripts tests`：clean。
- `compileall app`：OK。
- `scripts/check_text_encoding.ps1`：UTF-8 BOM 检查通过（含两个新增 PowerShell 脚本）。
- `scripts/verify_project.ps1`：完整链路（Python lint + pytest + smoke test + Android testGrayDebugUnitTest + assembleGrayDebug + assembleInternalDebug + lintGrayDebug）`项目验证完成。`

## 11. 安全 / 边界

- `/owner/backups`、`/web/*` 全部走 `app.network_boundary.require_owner_console_local`，与 Owner Console 同级；公网仍 403。
- `/api/admin/*` 默认 403，逻辑不变。
- 新文档与 PR body 不写真实 UploadLink / Pairing Code / Token。
- `git ls-files --others` 与 diff 中均未发现 `.apk` / `.db` / `uploads/` / `logcat` / `upl_…` token。

## 12. 不在本轮范围内

- 多账本切换（v0.4 地基）。
- 任何后端表结构 / 字段调整。
- 前端框架（Vue/React/Svelte 等）。
- 邮箱 / 手机号 / 密码体系。
- 自动合并 PR。

## 13. 最终判断

- **是否建议合并 main**：建议。所有测试 + verify_project 全绿，公网边界与 v0.3-rc1 保持一致，没有破坏性 schema / 接口变更。
- **是否影响 v0.3-rc1**：不影响。`v0.3-rc1-preflight` 验证过的公网行为（`/owner` 公网 403、`/api/admin/*` 公网 403、Cloudflare → `/api/health` → 200、UploadLink 单次合法上传）在本轮没有动过对应路径或依赖。
- **是否可进入 v0.4 多账本**：可以。备份服务、错误文案、Web 视图都按 `tenant_id == ledger_id` 模型实现，未引入新的全局假设；`owner_console_service.get_default_ledger_id` 返回首个非归档账本，已为后续多账本切换预留入口。
