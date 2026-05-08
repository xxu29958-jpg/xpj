# 小票夹后端

Windows 本机 FastAPI 服务。默认只监听 `127.0.0.1:8000`，由 Cloudflare Tunnel 映射到公网域名。

## 技术栈

- Python 3.11+
- FastAPI
- SQLite
- SQLAlchemy
- Pydantic
- Uvicorn
- Windows 11 本地运行
- 不使用 Docker
- 不依赖 Linux

## 初始化

推荐直接运行初始化脚本：

```bat
cd /d E:\projects\xiaopiaojia\backend
setup.bat
```

开发环境需要测试和 lint 工具时：

```bat
setup.bat -Dev
```

脚本会：

- 检查 Python 3.11+。
- 创建 `.venv`。
- 安装后端依赖。
- 创建 `data`、`uploads`、`logs`、`backups` 目录。
- 如果 `.env` 不存在，自动生成随机 `UPLOAD_TOKEN`、`APP_TOKEN`、`ADMIN_TOKEN`。

已有 `.env` 时脚本不会覆盖。确实要重建 Token 时才使用：

```bat
setup.bat -ForceEnv
```

也可以手工初始化：

```bat
cd /d E:\projects\xiaopiaojia\backend
py -3.11 -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env
```

请把 `.env` 中的三个 Token 换成随机长字符串。

示例：

```env
UPLOAD_TOKEN=replace-with-long-random-upload-token
APP_TOKEN=replace-with-long-random-app-token
ADMIN_TOKEN=replace-with-long-random-admin-token
DATABASE_URL=sqlite:///data/ticketbox.db
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE_MB=10
DELETE_IMAGE_AFTER_CONFIRM=false
GENERATE_THUMBNAIL=true
DELETE_IMAGE_AFTER_DAYS=0
OCR_PROVIDER=empty
OCR_AUTO_RUN=false
OCR_FALLBACK_PROVIDER=empty
OCR_MIN_CONFIDENCE=0.65
OCR_DEFAULT_TIMEZONE=Asia/Shanghai
LOCAL_LLM_BASE_URL=http://127.0.0.1:1234/v1
LOCAL_LLM_MODEL=
LOCAL_LLM_TIMEOUT_SECONDS=60
```

## 启动

```bat
run.bat
```

服务地址：

```text
http://127.0.0.1:8000
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

日志位置：

```text
backend\logs\backend-YYYYMMDD.log
backend\logs\ticketbox-backend-YYYYMMDD.out.log
backend\logs\ticketbox-backend-YYYYMMDD.err.log
```

查看服务器状态和最近访问日志：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\show_server_status.ps1
```

日常一键诊断：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_ticketbox.ps1 -Strict
```

## Windows 开机自启

推荐从项目根目录安装统一自启任务，同时处理后端和 Cloudflare Tunnel：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_service_status.ps1 -Strict
```

只安装后端任务时，也可以使用后端目录脚本：

```powershell
cd E:\projects\xiaopiaojia\backend
powershell -ExecutionPolicy Bypass -File scripts\install_startup_task.ps1
```

删除任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_startup_task.ps1
```

任务只运行 `scripts\start_backend.ps1`，默认监听 `127.0.0.1:8000`。

查看任务：

```powershell
Get-ScheduledTask -TaskName TicketboxBackend
```

长期运行、睡眠设置和外网诊断见 [Windows 长期运行 Runbook](../docs/WINDOWS_SERVICE_RUNBOOK.md)。

## 数据库备份

手动备份 SQLite 数据库：

```powershell
cd E:\projects\xiaopiaojia\backend
powershell -ExecutionPolicy Bypass -File scripts\backup_database.ps1
```

备份位置：

```text
backend\backups\
```

默认保留最近 30 个备份，可用 `-Keep` 修改：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup_database.ps1 -Keep 60
```

从备份恢复数据库：

```powershell
cd E:\projects\xiaopiaojia\backend
powershell -ExecutionPolicy Bypass -File scripts\restore_database.ps1 `
  -BackupFile backups\ticketbox-20260504-120000.db
```

恢复脚本只允许从 `backend\backups\ticketbox-*.db` 恢复，并会在覆盖前自动备份当前数据库。

## PowerShell 测试

以下命令假设服务已经启动，并且 `.env` 中：

```text
UPLOAD_TOKEN=upload-test-token
APP_TOKEN=app-test-token
ADMIN_TOKEN=admin-test-token
```

### 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

### App Token 检查

```powershell
$appHeaders = @{ Authorization = "Bearer app-test-token" }
Invoke-RestMethod http://127.0.0.1:8000/api/auth/check -Headers $appHeaders
```

### 创建测试图片

```powershell
[IO.File]::WriteAllBytes(
  "test.png",
  [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=")
)
```

### 上传截图

PowerShell 里建议使用 `curl.exe`，避免 `curl` 被 PowerShell alias 到 `Invoke-WebRequest`。

先校验上传 Token：

```powershell
curl.exe "http://127.0.0.1:8000/api/upload/check" `
  -H "Upload-Token: upload-test-token"
```

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/upload-screenshot" `
  -H "Upload-Token: upload-test-token" `
  -F "file=@test.png"
```

`multipart/form-data` 会优先读取 `file` 字段，也兼容 `image`、`photo`、`screenshot`，最后会取表单里的第一个文件字段。这样 iOS 快捷指令或其他客户端字段名略有差异时不会直接失败。

也可以直接上传原始图片请求体，方便对应 iOS 快捷指令的“文件”请求正文：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/upload-screenshot" `
  -H "Upload-Token: upload-test-token" `
  -H "Content-Type: image/png" `
  --data-binary "@test.png"
```

返回示例：

```json
{
  "id": 1,
  "public_id": "018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d",
  "status": "pending",
  "message": "uploaded",
  "upload_size_bytes": 68,
  "duration_ms": 21,
  "timing_ms": {
    "form_parse_ms": 3,
    "file_save_ms": 4,
    "db_create_ms": 7,
    "total_ms": 21
  }
}
```

`timing_ms` 只用于排查上传慢的问题。表单上传通常包含 `form_parse_ms`，原始图片请求体通常包含 `body_read_ms`。

### 查询待确认账单

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/expenses/pending -Headers $appHeaders
```

### 修改账单

```powershell
$body = @{
  amount_cents = 3680
  merchant = "美团外卖"
  category = "餐饮"
  note = "午饭"
  expense_time = "2026-05-03T04:20:00Z"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Patch `
  -Uri http://127.0.0.1:8000/api/expenses/1 `
  -Headers $appHeaders `
  -ContentType "application/json" `
  -Body $body
```

### 确认入账

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/expenses/1/confirm `
  -Headers $appHeaders
```

如果 `amount_cents` 为空，会返回：

```json
{
  "error": "amount_required",
  "message": "请先填写金额。"
}
```

### 查询已确认账单

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/expenses/confirmed?page=1&page_size=50&month=2026-05" `
  -Headers $appHeaders
```

### 查询分类列表

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/expenses/categories `
  -Headers $appHeaders
```

### 查询账单月份

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/expenses/months `
  -Headers $appHeaders
```

### 导出账本 CSV

```powershell
Invoke-WebRequest `
  -Uri "http://127.0.0.1:8000/api/expenses/export.csv?month=2026-05" `
  -Headers $appHeaders `
  -OutFile ticketbox-2026-05.csv
```

也可以使用项目脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\export_confirmed.ps1 `
  -AppToken app-test-token `
  -Month 2026-05 `
  -OutFile ticketbox-2026-05.csv
```

### 获取单条账单详情

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/expenses/1 `
  -Headers $appHeaders
```

### 获取受保护图片

```powershell
Invoke-WebRequest `
  -Uri http://127.0.0.1:8000/api/expenses/1/image `
  -Headers $appHeaders `
  -OutFile downloaded-test.png
```

### 获取受保护缩略图

```powershell
Invoke-WebRequest `
  -Uri http://127.0.0.1:8000/api/expenses/1/thumbnail `
  -Headers $appHeaders `
  -OutFile thumbnail-test.jpg
```

### OCR retry 入口

OCR 只生成待确认草稿，不会自动入账。当前支持：

```text
empty      不识别，只保留接口
mock       本地测试 provider
rapidocr   本地 RapidOCR，把图片转文字，再用规则提取金额/商家/时间
local_llm  OpenAI 兼容本地视觉模型服务，例如 http://127.0.0.1:1234/v1
```

安装本地 OCR 可选依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
```

启用本地 OCR：

```env
OCR_PROVIDER=rapidocr
OCR_AUTO_RUN=true
OCR_FALLBACK_PROVIDER=local_llm
```

如果没有本地模型服务，保持 `OCR_FALLBACK_PROVIDER=empty`。上传接口会优先保证保存成功，自动 OCR 失败不会影响 pending 创建；手动重试会返回错误。

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/expenses/1/ocr/retry `
  -Headers $appHeaders
```

### 粘贴文本识别

用于调试规则抽取，或以后从快捷指令/其他 OCR 把文本传给后端：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/expenses/1/recognize-text `
  -Headers $appHeaders `
  -ContentType application/json `
  -Body '{"raw_text":"中国建设银行\n交易时间：2026年5月4日 16:23:25\n交易金额：18.51（人民币）"}'
```

### 疑似重复账单

只返回仍需处理的疑似重复账单，已拒绝账单不会出现在这里。

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/duplicates `
  -Headers $appHeaders
```

### 标记为非重复

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/expenses/1/mark-not-duplicate `
  -Headers $appHeaders
```

这会记录当前疑似重复关系和检测类型，后续编辑同一组账单时不会反复出现同类型提示。

### 分类规则

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/rules/categories `
  -Headers $appHeaders
```

### 服务器状态

只返回非敏感运行状态，不返回 Token、本机路径或数据库路径。

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/settings/server `
  -Headers $appHeaders
```

删除分类规则：

```powershell
Invoke-RestMethod `
  -Method Delete `
  -Uri http://127.0.0.1:8000/api/rules/categories/1 `
  -Headers $appHeaders
```

### 月度统计

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/stats/monthly?month=2026-05" `
  -Headers $appHeaders
```

### 生活化统计

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/stats/lifestyle?month=2026-05" `
  -Headers $appHeaders
```

### 图片清理维护

维护接口使用 `ADMIN_TOKEN`。它只按 `DELETE_IMAGE_AFTER_DAYS` 清理已确认账单图片，不接收任意文件路径。

```powershell
$adminHeaders = @{ Authorization = "Bearer admin-test-token" }
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/maintenance/cleanup-images `
  -Headers $adminHeaders
```

### 拒绝待确认账单

只能拒绝 `pending` 账单。

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/expenses/1/reject `
  -Headers $appHeaders
```

## 安全边界

- 上传接口使用 `Upload-Token`。
- App 接口使用 `Authorization: Bearer APP_TOKEN`。
- 维护接口使用 `Authorization: Bearer ADMIN_TOKEN`。
- `uploads/` 不作为静态目录公开。
- 图片只能通过 `GET /api/expenses/{id}/image` 鉴权访问。
- 缩略图只能通过 `GET /api/expenses/{id}/thumbnail` 鉴权访问。
- API 不返回 Windows 本机真实路径。
- 上传文件随机命名。
- 单文件最大 10MB。
- 支持 `jpg`、`jpeg`、`png`、`webp`、`heic`。
- 数据库只保存图片相对路径。
- 默认只监听 `127.0.0.1:8000`。

## 后端验收

```bat
cd /d E:\projects\xiaopiaojia\backend
.venv\Scripts\python.exe -m compileall app scripts
.venv\Scripts\ruff.exe check app scripts
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe scripts\smoke_test.py
```

从项目根目录一键跑后端和 Android 验证：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\verify_project.ps1
```

实机联调预检：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\real_device_preflight.ps1 -SkipDevice
```
