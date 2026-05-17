# 小票夹安全说明

v0.3 隔离要求以账号 / 账本 / 设备模型为准，完整要求见 `docs/ACCOUNT_SYSTEM.md`。

核心底线：

- 账单不串账本。
- 图片不串账本。
- CSV 不串账本。
- 分类规则不串账本。
- 重复检测不跨账本。
- 普通 App 不显示服务器域名、token、Cloudflare、端口、日志或诊断脚本。

小票夹是私人本地优先软件，不按公网多用户系统设计。安全重点是保护凭证、图片、SQLite 数据库和 Windows 主机。

## v0.3 身份凭证模型

v0.3 废弃了旧版的 `APP_TOKEN`/`UPLOAD_TOKEN`/`ADMIN_TOKEN` 静态 token 模型，改为基于 SQLite 的可撤销凭证系统：

```text
PairingCode    Android 绑定入口，6 位数字，一次性，有 TTL（默认 15 分钟）
AuthToken      设备会话 token，Bearer 鉴权，可撤销
UploadLink     iPhone 上传入口，URL 路径携带 upload_key，可撤销
BootstrapAdmin 初始化时生成的 admin scope token，用于后续管理操作
```

规则：

- `PairingCode` 只用于 `POST /api/auth/pair`，成功后返回 `session_token`，PairingCode 立即失效。
- `PairingCode` 只保存 hash，消费时用原子条件更新保证一次性；同一来源短时间内失败过多会被限流。
- `AuthToken` 用于 Android App 调用账单、图片、统计、规则等接口，通过 `Authorization: Bearer <session_token>` 传递。
- `UploadLink` 用于 iPhone 快捷指令上传截图，通过完整 URL `POST /u/<upload_key>?tz=...` 传递，不需要额外请求头。
- `GET /api/settings/server` 只返回非敏感运行状态，不返回 Token、本机路径或数据库路径。
- `/api/auth/check` 是 Android 校验 session token 的唯一接口。
- `/api/health` 不代表任何凭证有效。
- 旧版 `APP_TOKEN`、`UPLOAD_TOKEN`、`TENANTS_JSON` 里的 token 请求一律返回 `legacy_auth_removed`（401）。
- 旧版静态 `ADMIN_TOKEN` 不再是运行时凭证；维护接口只接受数据库中保存 hash 的 admin scope token。
- 凭证不写入代码、README、提交记录、日志或截图。
- 因为 UploadLink 的 `upload_key` 在 URL 路径中，公网运行必须使用 `run.bat` / `backend\scripts\start_backend.ps1` 启动后端，或手动给 Uvicorn 加 `--no-access-log`，避免访问日志记录 `/u/{upload_key}`。
- 不要在 Cloudflare、反向代理、Windows 计划任务日志、故障截图或工单中记录完整 UploadLink URL。需要排查时只记录域名、时间、HTTP 状态、请求大小和响应错误码，`/u/<upload_key>` 必须打码。

## 图片

必须遵守：

- `uploads/` 不能通过 `StaticFiles` 或 Web 服务器直接公开。
- 图片只能通过鉴权接口读取。
- 原图接口是 `GET /api/expenses/{id}/image`。
- 缩略图接口是 `GET /api/expenses/{id}/thumbnail`。
- API 返回不能暴露 Windows 真实路径。
- 数据库只保存相对路径。
- 上传文件使用随机文件名，不使用原始文件名。

上传校验：

- 只接受 `jpg`、`jpeg`、`png`、`webp`、`heic`。
- 单文件默认最大 10MB。
- 校验扩展名或 content-type 后，还会检查图片文件头。
- `jpg`、`jpeg`、`png`、`webp` 会通过 Pillow `verify()` 做可解码校验。
- `heic` 通过 `pillow-heif` 注册到 Pillow 后做真实解码校验；伪造 `ftyp` brand 但不可解码的 HEIC 会被拒绝。
- HEIC 原图会保存到受保护上传目录，并尝试生成 JPEG 缩略图；缩略图失败不阻断 pending 创建。

## 数据库

- SQLite 数据库只给本机 FastAPI 服务访问。
- 不提供数据库下载、文件管理、命令执行、远程关机等危险接口。
- API 只返回业务字段，不返回真实数据库路径。
- CSV 导出只返回已确认账单业务数据，不提供任意文件下载或目录浏览。
- Windows 备份脚本使用 SQLite Online Backup API 将 `backend\data\ticketbox.db` 快照到 `backend\backups`，清理旧备份前会校验目标仍在备份目录内。
- 数据库恢复脚本只允许从 `backend\backups\ticketbox-*.db` 恢复，覆盖前会使用 SQLite Online Backup API 自动备份当前数据库。
- v0.3 启动时如果发现数据库仍是 pre-v0.3 结构，会在迁移前创建 `backups\ticketbox-pre-v0.3-YYYYMMDD-HHMMSS.db` 备份。
- 身份表迁移完成后，后续重启不会重复生成新的 `pre-v0.3` 备份；回滚时使用首次迁移前的备份。

## 维护接口

维护接口使用 admin token（`Authorization: Bearer <admin_token>`），只作用于当前 admin 上下文对应的账本。

限制：

- 不接收任意文件路径。
- 不提供目录浏览、文件下载、文件删除等通用文件管理能力。
- 清理前会校验目标相对路径必须位于后端 `uploads/{ledger_id}/` 目录内。
- `DELETE_IMAGE_AFTER_DAYS <= 0` 时不执行删除。

## 网络暴露

默认监听：

```text
127.0.0.1:8000
```

不要监听：

```text
0.0.0.0
```

公网访问只通过 Cloudflare Tunnel：

```text
api.我的域名.com -> http://127.0.0.1:8000
```

不要开放路由器端口。

不要把 Windows 文件夹映射到公网。

## Android 客户端

- Session token 使用 Android Keystore 保存。
- BiometricPrompt 只用于本地解锁 Token，不替代服务端鉴权。
- OkHttp 日志不得打印 Header、Body 或 Token。
- 清除绑定必须清除服务器地址、Token 和本地解锁状态。
- confirmed 账单同步到 Room 时必须按 `serverId` 唯一 upsert。

## 错误返回

所有错误必须保持统一格式：

```json
{
  "error": "错误代码",
  "message": "中文错误说明"
}
```

禁止返回 traceback、底层英文异常、本机路径或 Token。
