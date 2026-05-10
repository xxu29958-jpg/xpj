# v0.3.2 自用稳定版 验收清单

> 适用版本：`v0.3.2-selfuse`（基线 = `v0.3.1-alpha2` + Owner Console UX hotfix + 公网边界加固）。
> 当前阶段：`v0.3-rc1-preflight`（公网边界与 iPhone UploadLink 公网链路已经实测通过，
> 见 [`docs/V0_3_RC1_PREFLIGHT_REPORT.md`](V0_3_RC1_PREFLIGHT_REPORT.md)）。
>
> 本文档**不是家庭正式版指南**，也**不是 rc1 终验**。它的目标是把"我自己一个人能稳定用"这件事跑通并固化。
> rc1 形式态还要求真机 iPhone Shortcut 与持机走一遍 confirmed 缓存恢复，详见上面 preflight 报告第 9 节。

## 适用范围

- 后端：Windows 原生 `uvicorn + FastAPI + SQLite`
- 公网入口：Cloudflare Tunnel → `127.0.0.1:8000`
- iPhone：iOS 快捷指令 → UploadLink URL
- Android：Compose App，`grayDebug` 构建，pairing code 绑定，confirmed 缓存
- Owner Console：本机 `127.0.0.1:8000/owner` HTML 管理面板

## v0.3.2 目标

```text
v0.3.2 = Windows 后端 + Owner Console + Android 恢复 + iPhone 上传链接 稳定自用。
不引入 Linux / WSL / Docker / Node / Vue。
不做家庭多账本切换、Android 通知监听、家庭账本正式发布。
```

## 自用验收门禁

下列每一项必须通过，才能把当前快照标为 `v0.3.2 self-use stable candidate`：

### 后端 / Owner Console

- [ ] `setup.bat` / `run.bat` 可在 Windows 直接跑，无 WSL。
- [ ] `GET /api/health` 返回 `status: ok`，含 `owner_console_status: available`。
- [ ] `/owner`、`/owner/devices`、`/owner/pairing`、`/owner/upload-links`、`/owner/diagnostics` 全部 `200`，中文渲染正常，无英文 traceback。
- [ ] Owner Console 仅允许 loopback（`127.0.0.1`/`::1`/`localhost`），远端访问被 403。
- [ ] `pytest` 全绿（≥128 passed）。
- [ ] `ruff check` 通过。
- [ ] `python -m compileall app scripts tests` 通过。
- [ ] `scripts\smoke_test.py` 通过。
- [ ] `scripts\verify_project.ps1` 通过（含 Android `assembleGrayDebug` / `lintGrayDebug` / unit test）。
- [ ] `scripts\check_text_encoding.ps1` 通过。

### UploadLink 安全

- [ ] 列表页只显示 `/u/***` 掩码。
- [ ] 完整 `/u/<key>?tz=...` 仅在新建/轮换后一次性显示，离开页面即不可见。
- [ ] **不再出现 `?tz=...?tz=...` 双重参数。**
- [ ] 模板里 `upload_url_path` 不被再次拼 `?tz`（由 `admin_service._upload_url_path` 一次性生成）。
- [ ] 中间件 `SanitizedLoggingMiddleware` 已挂载，`/u/{key}` / `Authorization` / `X-Bootstrap-Secret` 在日志中被脱敏。

### 设备管理

- [ ] 设备列表显示账号 / 账本 / 最近使用 / 状态，时间为 `YYYY-MM-DD HH:MM` 形式（不再是裸 ISO）。
- [ ] 不展示数据库自增 `id`、`token_hash`、`session_token`。
- [ ] 设备「停用」可用：弹确认 → 状态变为「已停用」→ 操作按钮消失。
- [ ] 当前 admin 自身的设备无法被自己停用（接口返回 409）。

### 绑定码

- [ ] 绑定码页生成 6 位数字，醒目展示。
- [ ] 有效期显示为 `YYYY-MM-DD HH:MM UTC`。

### Android 完整链路

参见 `docs\REAL_DEVICE_RUNBOOK.md` + `scripts\run_android_pairing_e2e.ps1`。

- [ ] `adb devices` 显示目标设备 `device`（authorized）。
- [ ] `assembleGrayDebug` 成功；APK 可 `adb install -r -d` 到机。
- [ ] App 启动无 `FATAL EXCEPTION`，logcat 无 `AndroidRuntime` 崩溃。
- [ ] 在 Owner Console 生成 6 位 pairing code，App 输入后绑定成功，状态显示「已连接 · owner」。
- [ ] 绑定后从清空状态恢复：confirmed 账单可见（DB `expense.status=confirmed` 至少一条）。
- [ ] 飞行模式下账本页显示「已确认支出 · 可离线查看」，缓存的 confirmed 仍能渲染。
- [ ] 飞行模式关闭后恢复正常，pending 票据继续可上传/确认。

### iPhone 快捷指令

- [ ] `docs\IOS_SHORTCUT.md` 仅推荐 UploadLink URL 方案；旧 `Upload-Token` 主路径已移除。
- [ ] 完整 URL 形如 `https://<域名>/u/<key>?tz=Asia/Shanghai`，**只有一个** `?tz=`。
- [ ] 真机一次成功上传记录（手工，本轮可暂不强制）。

### Git / 仓库卫生

- [ ] `git status --short` 干净，无意外残留。
- [ ] `git diff --check` 无空白错误。
- [ ] 没有把 `*.db / *.sqlite / uploads / artifacts / logcat / *.png 截图 / token / secret / bootstrap` 提交进 git。

### 红线

- [ ] **未恢复**旧 `APP_TOKEN` / `UPLOAD_TOKEN` runtime fallback。
- [ ] **未公开** `uploads/`，未把 FastAPI 改成 `0.0.0.0`。
- [ ] **未** force push `main`，**未**直接推 `codex/split-large-files`。
- [ ] **未**引入 Linux / WSL / Docker / Node / Vue 前置依赖。

## 进入 rc1 的额外条件（不在本轮强制）

```text
1. 真实自用 24-48 小时无明显问题。
2. iPhone 快捷指令真实上传成功（含 Cloudflare 链路）。
3. Android 卸载重装重新绑定 confirmed 恢复至少再跑一次。
4. Owner Console 不再出现展示层明显 bug。
5. 没有安全泄露（token_hash / session token / upload_key 不出现在 UI/日志）。
```

## 开发期辅助脚本（注意）

下列脚本会**重置**或**写入**开发库 / 上传目录，**真实数据环境不要执行**：

```text
backend\scripts\reset_dev_db.ps1
backend\scripts\reset_dev_uploads.ps1
backend\scripts\seed_dev_confirmed.ps1
backend\scripts\bootstrap_dev_owner.ps1
```

## 相关文档

- `docs\REAL_DEVICE_RUNBOOK.md` — 实机端到端联调
- `docs\GRAY_ACCEPTANCE_EXECUTION.md` — 灰度验收执行
- `docs\WINDOWS_SERVICE_RUNBOOK.md` — Windows 计划任务/服务化
- `docs\IOS_SHORTCUT.md` — iPhone 快捷指令
- `docs\ACCOUNT_SYSTEM.md` — 账号 / 账本 / 设备身份模型
- `docs\API.md` — API 契约
- `docs\SECURITY.md` — 安全边界
