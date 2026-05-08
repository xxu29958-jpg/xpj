# 小票夹安全说明

灰度版新增多租户隔离要求。完整要求见 `docs/MULTI_TENANT_SPEC.md`。

核心底线：

- 账单不串租户。
- 图片不串租户。
- CSV 不串租户。
- 分类规则不串租户。
- 重复检测不跨租户。
- 普通 App 不显示服务器域名、token、Cloudflare、端口、日志或诊断脚本。

小票夹是私人本地优先软件，不按公网多用户系统设计。安全重点是保护 Token、图片、SQLite 数据库和 Windows 主机。

## Token

后端使用三个 Token：

```text
UPLOAD_TOKEN  iPhone 快捷指令上传图片使用
APP_TOKEN     Android App 访问账单接口使用
ADMIN_TOKEN   维护接口使用
```

规则：

- `UPLOAD_TOKEN` 只能用于 `/api/upload-screenshot`。
- `APP_TOKEN` 用于账单、图片、统计、规则等 App 接口。
- `GET /api/settings/server` 只返回非敏感运行状态，不返回 Token、本机路径或数据库路径。
- `ADMIN_TOKEN` 只用于 `/api/maintenance/*` 这类窄维护接口。
- `/api/auth/check` 是 Android 绑定服务器的唯一 Token 校验接口。
- `/api/health` 不代表 Token 正确。
- Token 不写入代码、README、提交记录、日志或截图。

## 图片

必须遵守：

- `uploads/` 不能通过 `StaticFiles` 或 Web 服务器直接公开。
- 图片只能通过鉴权接口读取。
- 原图接口是 `GET /api/expenses/{id}/image`。
- 缩略图接口是 `GET /api/expenses/{id}/thumbnail`。
- API 不返回 Windows 真实路径。
- 数据库只保存相对路径。
- 上传文件使用随机文件名，不使用原始文件名。

上传校验：

- 只接受 `jpg`、`jpeg`、`png`、`webp`、`heic`。
- 单文件默认最大 10MB。
- 校验扩展名或 content-type 后，还会检查图片文件头。
- HEIC 第一版可以保存，但不保证 Android 预览。

## 数据库

- SQLite 数据库只给本机 FastAPI 服务访问。
- 不提供数据库下载、文件管理、命令执行、远程关机等危险接口。
- API 只返回业务字段，不返回真实数据库路径。
- CSV 导出只返回已确认账单业务数据，不提供任意文件下载或目录浏览。
- Windows 备份脚本只复制 `backend\data\ticketbox.db` 到 `backend\backups`，清理旧备份前会校验目标仍在备份目录内。
- 数据库恢复脚本只允许从 `backend\backups\ticketbox-*.db` 恢复，覆盖前会自动备份当前数据库。

## 维护接口

`POST /api/maintenance/cleanup-images` 使用 `ADMIN_TOKEN`，只按配置清理当前 admin 上下文租户的已确认账单图片和缩略图。当前实现中 `ADMIN_TOKEN` 映射到默认租户，不提供全局后台。

限制：

- 不接收任意文件路径。
- 不提供目录浏览、文件下载、文件删除等通用文件管理能力。
- 清理前会校验目标相对路径必须位于后端 `uploads/{tenant_id}/` 目录内。
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

- APP_TOKEN 使用 Android Keystore 保存。
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
