# 小票夹完整架构

## 灰度版总入口

当前开发基准以 v0.3 账号 / 账本 / 设备身份模型为准。完整要求见：

```text
docs/ACCOUNT_SYSTEM.md
docs/BOOTSTRAP.md
docs/API.md
docs/SECURITY.md
docs/ANDROID_RULES.md
docs/ANDROID_STATE_FLOW.md
docs/ANDROID_UPLOAD.md
docs/RELEASE_PACKAGING.md
docs/GRAY_ACCEPTANCE_EXECUTION.md
```

灰度版强制要求：

- 普通用户主体验不显示服务器域名、token、接口名、Cloudflare、端口、日志和诊断脚本。
- 多账本按 `ledger_id` 隔离账单、图片、统计、分类规则、重复检测和 CSV。
- iPhone 快捷指令和 Android App 均可上传截图。
- OCR 只填草稿，不自动入账。
- Release 包和 Windows 运维诊断分层提供。

## 1. 项目定位

小票夹是一个私人半自动记账系统，面向个人和灰度试用使用，不做商业云服务。当前核心目标是让账单截图从 iPhone 或 Android 进入 Windows 后端，由 OCR/规则生成草稿，再由 Android App 人工确认入账。

当前已实现重点：

- iPhone 截图上传。
- Android 截图上传。
- Windows FastAPI 后端保存截图。
- 后端创建 pending 待确认账单，并可按配置运行 OCR 草稿识别。
- Android App 拉取 pending 账单。
- 用户编辑金额、商家、分类、消费时间、备注。
- 用户确认或拒绝账单。
- confirmed 账单同步到 Android Room 本地缓存。
- v0.3 身份系统：Account、Ledger、Device、AuthToken、UploadLink、PairingCode。
- 多账本隔离账单、图片、统计、分类规则、重复检测和导出。
- 分类规则、重复检测、缩略图和图片清理维护接口已落地。

当前明确不做：

- 商业账号注册和登录系统。
- 邮箱、手机号、第三方登录。
- 远程控制电脑。
- 云端商业部署。
- 自动读取 iPhone 相册。
- 自动入账。
- 微信、支付宝自动监听。
- 银行卡接口。
- 第三方支付接口。

> v0.3.3 起后端已提供本机轻量网页版账本 `/web`（loopback only），v0.4-alpha1
> 起本机 Owner Console 增加 `/owner/ledgers` 多账本管理入口；二者**仍只允许
> loopback 访问**，不通过 Cloudflare Tunnel 暴露到公网，也不是商业 Web 后台。

## 2. 总体流程

```text
iPhone 截图
  -> iOS 快捷指令上传图片
  -> https://api.我的域名.com/u/<upload_key>
  -> Cloudflare Tunnel
  -> Windows 主机 FastAPI 服务，监听 127.0.0.1:8000
  -> SQLite 数据库 + uploads 私有图片目录
  -> Android App 拉取 pending 账单
  -> 用户编辑/确认/删除
  -> confirmed 账单同步到 Android Room
```

系统边界：

- iPhone 只负责上传图片。
- 后端只负责保存、校验、建账单、提供 API。
- Android App 是当前唯一人工确认入口。
- SQLite 数据库只能被本机后端访问。
- uploads 目录不能被静态公开。
- Cloudflare Tunnel 只映射 API，不映射 Windows 文件夹。

## 3. 后端技术栈

- Python 3.11+
- FastAPI
- SQLite
- SQLAlchemy
- Pydantic
- Uvicorn
- Windows 11 可运行
- 不依赖 Linux
- 不依赖 Docker

推荐目录：

```text
backend/
  app/
    main.py
    config.py
    database.py
    models.py
    schemas.py
    auth.py
    errors.py
    tenants.py
    routes/
      auth.py
      bootstrap.py
      health.py
      expenses.py
      uploads.py
      stats.py
      settings.py
      maintenance.py
      rules.py
      duplicates.py
    services/
      file_service.py
      expense_service.py
      time_service.py
      identity_service.py
```

职责划分：

- `main.py`：创建 FastAPI app、注册路由、注册统一异常处理。
- `config.py`：读取 `.env` 或环境变量。
- `database.py`：SQLite engine、session、建表入口。
- `models.py`：数据库 ORM 模型（含 Account、Ledger、Device、AuthToken、UploadLink、PairingCode）。
- `schemas.py`：Pydantic 请求和响应模型。
- `auth.py`：`Authorization: Bearer` 校验、旧版 token 检测。
- `tenants.py`：`AuthContext` 运行时身份上下文。
- `errors.py`：统一错误结构。
- `routes/`：HTTP 层。
- `services/`：业务逻辑和文件处理。
- `services/identity_service.py`：核心身份逻辑（绑定、鉴权、初始化）。

## 4. 后端配置

`.env` 示例：

```env
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

> **注意**：v0.3 不再在 `.env` 中配置 `APP_TOKEN`、`UPLOAD_TOKEN`、`ADMIN_TOKEN`。旧 app/upload token 已被废弃，运行时请求使用它们会返回 `legacy_auth_removed`；旧静态 admin token 不再是有效维护凭证。

`run.bat`：

```bat
@echo off
cd /d %~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start_backend.ps1 -Port 8000
```

`start_backend.ps1` 会使用 `--no-access-log` 启动 Uvicorn，避免 UploadLink URL 中的 `upload_key` 出现在访问日志里。

后端默认只监听：

```text
127.0.0.1:8000
```

不要监听 `0.0.0.0`。

## 5. v0.3 身份与权限

v0.3 废弃了旧版三个静态 Token（`UPLOAD_TOKEN`、`APP_TOKEN`、`ADMIN_TOKEN`），改为基于 SQLite 的可撤销凭证系统：

```text
PairingCode    Android 绑定入口，6 位数字，一次性，有 TTL（默认 15 分钟）
AuthToken      设备会话 token，Bearer 鉴权，可撤销
UploadLink     iPhone 上传入口，URL 路径携带 upload_key，可撤销
BootstrapAdmin 初始化时生成的 admin token，用于维护接口
```

请求头：

```http
Authorization: Bearer <session_token>
```

```http
Authorization: Bearer <admin_token>
```

认证规则：

- `POST /api/auth/pair` 不需要鉴权，用 Pairing Code 换取 session token。
- `POST /api/bootstrap/owner` 默认禁用（返回 `404 bootstrap_disabled`）。仅当后端运行环境显式设置 `ENABLE_HTTP_BOOTSTRAP=true` 并配置 `HTTP_BOOTSTRAP_SECRET` 时可用，调用方必须携带 `X-Bootstrap-Secret` 请求头；secret 一次性消费。loopback 不再用作鉴权依据，Cloudflare Tunnel 公网无法绕过。详见 [BOOTSTRAP.md](BOOTSTRAP.md)。
- `POST /api/bootstrap/pairing-codes` 需要 admin token。
- `/u/{upload_key}` 通过 URL 路径中的 upload_key 鉴权，不需要 header。
- Android App 接口需要 `Authorization: Bearer <session_token>`。
- `/api/maintenance/*` 需要 `Authorization: Bearer <admin_token>`，并只作用于当前 admin 上下文对应的账本。
- `/api/auth/check` 必须验证 session token。
- `/api/health` 可以不鉴权，只用于本地或隧道健康检查。
- 旧版 `APP_TOKEN`、`UPLOAD_TOKEN`、`TENANTS_JSON` app/upload token 一律返回 `legacy_auth_removed`（401）；旧静态 admin token 按无效凭证处理。

## 6. 统一错误格式

所有错误统一返回：

```json
{
  "error": "错误代码",
  "message": "中文错误说明"
}
```

常见错误代码：

```text
invalid_token
legacy_auth_removed
bootstrap_already_initialized
invalid_pairing_code
pairing_code_expired
pairing_code_used
file_too_large
unsupported_file_type
expense_not_found
amount_required
server_error
invalid_request
route_not_found
method_not_allowed
```

示例：

```json
{
  "error": "amount_required",
  "message": "请先填写金额。"
}
```

## 7. 金额规则

全链路不使用 float 保存金额。

后端：

```text
amount_cents: int?
```

Android Room：

```text
amountCents: Long?
```

单位统一为"分"。界面显示时转换为元：

```text
3680 -> ¥36.80
```

确认入账时，如果 `amount_cents` 为空，后端必须拒绝确认并返回 `amount_required`。

## 8. 时间规则

所有时间使用 ISO 8601 字符串。

数据库保存 UTC 时间：

```text
created_at      上传/创建时间
updated_at      最近更新时间
expense_time    实际消费时间，可为空
confirmed_at    确认入账时间，可为空
rejected_at     拒绝时间，可为空
```

统计默认按：

```text
expense_time 优先
如果 expense_time 为空，则使用 confirmed_at
```

Android 展示时转本地时区。

## 9. Expense 数据模型

```text
id: int，自增主键
public_id: string，公共 UUID，用于导出、同步和排查
amount_cents: int?，金额，单位分
merchant: string?，商家
category: string，默认 其他
note: string?，备注
source: string，默认 iPhone截图
image_path: string?，相对路径
image_hash: string?，图片 sha256，用于当前账本内完全重复检测
raw_text: string?，OCR 原文或快捷指令文本识别结果
confidence: float?，OCR 置信度
status: string，pending / confirmed / rejected
expense_time: datetime?，实际消费时间，UTC
created_at: datetime，上传/创建时间，UTC
updated_at: datetime，更新时间，UTC
confirmed_at: datetime?，确认时间，UTC
rejected_at: datetime?，拒绝时间，UTC
```

分类默认值：

```text
餐饮
交通
购物
娱乐
医疗
教育
住房
通讯
AI订阅
数码
游戏
生活
其他
```

旧版 `吃饭` 作为兼容别名归一到 `餐饮`。新写入、统计和筛选统一使用归一后的分类。

状态机：

```text
pending -> confirmed
pending -> rejected
confirmed -> confirmed，允许继续 PATCH 修正
rejected 当前不恢复，普通列表默认不展示
```

## 10. 图片保存规则

上传图片保存到账本目录：

```text
backend/uploads/{ledger_id}/YYYY/MM/
```

要求：

- 只接受 `jpg`、`jpeg`、`png`、`webp`、`heic`。
- 单个文件最大 10MB。
- 保存前生成随机文件名。
- 不使用原始文件名。
- 计算 `image_hash`，用于当前账本内重复检测；重复只提示，不自动删除、不自动拒绝、不自动入账。
- `image_path` 只保存相对路径。
- API 返回不能暴露 Windows 真实路径。
- uploads 不能作为公开静态目录。
- 支持按配置确认后删除原图、按保留天数清理图片；默认不自动删除。

iPhone 快捷指令建议上传前转为 JPEG 或 PNG。后端可以接受 HEIC 原图，但当前缩略图生成会跳过 HEIC，Android 端需要降级处理。

## 11. 后端 API

### 健康检查

```http
GET /api/health
```

返回：

```json
{
  "status": "ok"
}
```

### 认证检查

```http
GET /api/auth/check
Authorization: Bearer <session_token>
```

返回：

```json
{
  "status": "ok",
  "account_name": "Owner",
  "ledger_name": "我的小票夹",
  "device_name": "小米 15 Pro",
  "role": "owner",
  "scope": "app"
}
```

Android 绑定后校验 session token 使用。

### 设备绑定

```http
POST /api/auth/pair
```

请求体：

```json
{
  "pairing_code": "738294",
  "device_name": "小米 15 Pro",
  "platform": "Android"
}
```

返回 session token，Android 保存到 Keystore。

### Owner 初始化

```http
POST /api/bootstrap/owner
```

仅首次可用，返回 admin token、upload key、pairing code 等只显示一次的凭证。

### 上传截图

```http
POST /u/<upload_key>?tz=Asia/Shanghai
User-Agent: TicketBox/1.0 iOS-Shortcut
Content-Type: image/jpeg 或 image/png
```

请求体：

```text
原始图片文件内容
```

后端也兼容标准 `multipart/form-data` 字段 `file`，但 iOS 26.4 快捷指令实测首选"请求正文：文件"，不要首选"表单"。

行为：

- 通过 URL 路径中的 `upload_key` 鉴权。
- 校验文件类型。
- 校验文件大小。
- 保存图片到 `uploads/{ledger_id}/YYYY/MM/`。
- 生成随机文件名。
- 计算 `image_hash`。
- 创建一条 pending expense。
- 根据配置运行 OCR provider 和规则解析，填充 `amount_cents`、`merchant`、`raw_text`、`confidence`、`expense_time`、`category` 等草稿字段；默认 `OCR_PROVIDER=empty` 且 `OCR_AUTO_RUN=false`。
- `category` 默认 `其他`。
- `status = pending`。

返回：

```json
{
  "id": 1,
  "public_id": "018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d",
  "status": "pending",
  "message": "uploaded"
}
```

### 获取待确认账单

```http
GET /api/expenses/pending
Authorization: Bearer <session_token>
```

返回 pending 账单列表。

### 获取已确认账单

```http
GET /api/expenses/confirmed?page=1&page_size=50&month=2026-05&category=餐饮
Authorization: Bearer <session_token>
```

参数：

```text
page: int，默认 1
page_size: int，默认 50
month: YYYY-MM，可选
category: string，可选
```

返回：

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total": 0
}
```

### 修改账单

```http
PATCH /api/expenses/{id}
Authorization: Bearer <session_token>
Content-Type: application/json
```

请求体：

```json
{
  "amount_cents": 3680,
  "merchant": "美团外卖",
  "category": "餐饮",
  "note": "午饭",
  "expense_time": "2026-05-03T04:20:00Z"
}
```

行为：

- 只能修改 pending 或 confirmed 账单。
- 更新 `updated_at`。
- 不允许直接通过 PATCH 写入危险字段，例如 `image_path`、`image_hash`。

### 确认入账

```http
POST /api/expenses/{id}/confirm
Authorization: Bearer <session_token>
```

行为：

- 如果 `amount_cents` 为空，返回 `amount_required`。
- `status` 改为 `confirmed`。
- `confirmed_at` 设置当前 UTC 时间。
- 更新 `updated_at`。

### 拒绝待确认账单

```http
POST /api/expenses/{id}/reject
Authorization: Bearer <session_token>
```

行为：

- `status` 改为 `rejected`。
- `rejected_at` 设置当前 UTC 时间。
- 更新 `updated_at`。

### 获取受保护图片

```http
GET /api/expenses/{id}/image
Authorization: Bearer <session_token>
```

行为：

- 校验 session token。
- 查询 expense。
- 根据数据库中的相对 `image_path` 读取本地文件。
- 返回图片流。
- 不返回真实本机路径。
- 不把 uploads 设置成静态目录。

### 本月统计

```http
GET /api/stats/monthly?month=2026-05
Authorization: Bearer <session_token>
```

统计口径：

- 只统计 `confirmed`。
- 优先按 `expense_time` 归月。
- 如果 `expense_time` 为空，则按 `confirmed_at` 归月。

返回：

```json
{
  "month": "2026-05",
  "total_amount_cents": 123456,
  "count": 30,
  "by_category": [
    {
      "category": "餐饮",
      "amount_cents": 52050,
      "count": 18
    },
    {
      "category": "数码",
      "amount_cents": 69900,
      "count": 1
    }
  ]
}
```

## 12. Android 技术栈

- Kotlin
- Jetpack Compose
- Material 3
- Room
- Retrofit
- Kotlin Coroutines
- Android BiometricPrompt
- Android Keystore
- 深色模式优先
- 中文界面

推荐目录：

```text
android/
  app/
    src/main/java/com/ticketbox/
      MainActivity.kt
      data/
        local/
          AppDatabase.kt
          ExpenseEntity.kt
          ExpenseDao.kt
        remote/
          ApiService.kt
          ApiClient.kt
          dto/
        repository/
          ExpenseRepository.kt
      domain/
        model/
          Expense.kt
      ui/
        theme/
        navigation/
        screens/
          BindServerScreen.kt
          PendingScreen.kt
          LedgerScreen.kt
          StatsScreen.kt
          SettingsScreen.kt
          ExpenseEditScreen.kt
        components/
      security/
        BiometricAuthManager.kt
        SecureTokenStore.kt
      viewmodel/
        PendingViewModel.kt
        LedgerViewModel.kt
        StatsViewModel.kt
        SettingsViewModel.kt
```

Android 数据流：

```text
Compose Screen
  -> ViewModel
  -> Repository
  -> Retrofit API + Room DAO
  -> UI State
```

## 13. Android 绑定与登录

当前不做账号密码。

首次打开：

```text
绑定我的账本
  -> 输入服务器地址，例如 https://api.我的域名.com
  -> 输入 6 位绑定码（Pairing Code）
  -> 调用 POST /api/auth/pair
  -> 保存 session token 到 Android Keystore
  -> 保存服务器地址和账号 / 账本 / 设备 / 角色
  -> 用新 session token 调用 syncConfirmed() 完整拉取 confirmed
  -> 替换 Room confirmed 缓存
  -> 进入 App
```

`POST /api/auth/pair` 成功后，Pairing Code 已被服务端消费。Android 必须先保存服务器地址、session token 和身份信息，再执行 confirmed 恢复；如果恢复失败，绑定仍然成立，只提示用户稍后在账本页更新。

后续打开：

```text
显示 小票夹
  -> 弹出指纹/面容验证
  -> 验证成功后读取 Keystore 中的 session token
  -> 进入主界面
```

安全要求：

- 指纹只用于解锁本地 Token。
- 服务器仍然通过 `Authorization: Bearer <session_token>` 校验。
- App 切到后台超过 5 分钟，再回来需要重新验证。
- 设置页提供"清除绑定"。
- 卸载重装后需要重新获取 Pairing Code 绑定。

## 14. Android 页面

底部导航：

```text
待确认
账本
统计
设置
```

整体风格：

- 深色模式。
- 卡片式布局。
- 圆角。
- 温和、生活化。
- 不要像财务后台系统。
- 不要过度复杂。

### 待确认页

功能：

- 打开页面时请求 `/api/expenses/pending`。
- 下拉刷新。
- 显示所有 pending 账单。
- 每条显示截图缩略图或"截图已上传"。
- 点击卡片进入编辑页。

卡片字段：

```text
商家
金额
分类
创建时间
消费时间
备注
截图状态
```

金额为空时显示：

```text
待填写金额
```

卡片按钮：

```text
编辑
确认
删除
```

确认前如果 `amount_cents` 为空，提示：

```text
请先填写金额。
```

### 编辑账单页

字段：

```text
金额，界面单位元，提交时转分
商家
分类
备注
消费时间
来源
OCR 原文，可折叠；未识别时为空
```

按钮：

```text
保存
确认入账
删除
```

行为：

- 保存调用 `PATCH /api/expenses/{id}`。
- 确认调用 `POST /api/expenses/{id}/confirm`。
- 删除调用 `POST /api/expenses/{id}/reject`。
- 确认成功后，本地 Room upsert 一份 confirmed 账单。

### 账本页

功能：

- 显示 confirmed 账单。
- 默认显示本月。
- 支持按分类筛选。
- 支持按月份筛选。
- 打开页面时从服务器同步 confirmed。
- 服务器不可用时显示本地 Room 缓存。

每条显示：

```text
金额
商家
分类
消费时间
备注
```

### 统计页

当前统计：

```text
本月总支出
本月账单数量
各分类支出
最大一笔支出
最近 7 天支出
```

Android 使用 Compose 卡片、列表和图表展示，不要求后台报表式复杂大屏。

### 设置页

功能：

```text
显示当前账本
检查连接
更新账本
清除本地缓存
清除服务器绑定
管理分类规则
关于小票夹
```

提示文案：

```text
小票夹是私人半自动账本。截图上传后不会自动入账，需要你确认后才会记录。
```

## 15. Android Room 模型

`ExpenseEntity`：

```text
id: Long，本地主键
serverId: Long，唯一
publicId: String，唯一
amountCents: Long?
merchant: String?
category: String
note: String?
source: String
rawText: String?
imageHash: String?
status: String
expenseTime: String?
createdAt: String
confirmedAt: String?
updatedAt: String?
```

本地保存策略：

- pending 可以不强制保存，也可以缓存。
- confirmed 必须保存。
- `serverId` 和 `publicId` 必须唯一。
- 同步 confirmed 时，如果 `serverId` 已存在，则更新，不重复插入。
- 服务器不可用时，账本页展示本地 confirmed。

## 16. iPhone 快捷指令

快捷指令名称：

```text
上传到小票夹
```

流程：

```text
从分享菜单接收图片
  -> 获取图片文件
  -> 建议转换为 JPEG 或 PNG
  -> 使用 获取 URL 内容
  -> 方法 POST
  -> URL: https://api.我的域名.com/u/<upload_key>?tz=Asia/Shanghai
  -> 请求正文选择 文件
  -> 文件选择 转换后的图像
  -> 添加 User-Agent: TicketBox/1.0 iOS-Shortcut 请求头
  -> 成功后显示 已上传到小票夹
```

UploadLink URL：

```text
https://api.我的域名.com/u/<upload_key>?tz=Asia/Shanghai
```

请求头：

```http
User-Agent: TicketBox/1.0 iOS-Shortcut
```

> **注意**：v0.3 不再使用 `Upload-Token` header。旧快捷指令使用旧 token 会收到 `legacy_auth_removed`。

失败时显示后端返回的中文错误信息。

## 17. Cloudflare Tunnel

本地后端：

```text
http://127.0.0.1:8000
```

Tunnel 映射：

```text
api.我的域名.com -> http://127.0.0.1:8000
```

要求：

- 不开放路由器端口。
- 不直接暴露 Windows 文件夹。
- 不把 uploads 设置成公开目录。
- 不把 SQLite 数据库目录暴露到公网。
- FastAPI 只监听 `127.0.0.1`。

## 18. 安全注意事项

必须遵守：

- 所有业务 API 都校验 Token。
- 上传接口只接受图片白名单格式。
- 上传文件最大 10MB。
- 上传文件必须使用随机文件名。
- 不使用原始文件名保存。
- uploads 文件夹不能公开。
- SQLite 数据库只本地访问。
- 不提供远程关机、命令执行、文件管理等危险接口。
- API 不返回本机真实路径。
- 图片路径只保存相对路径。
- 受保护图片接口必须验证 session token。
- 支持确认后删除原图和按天数清理图片，删除必须限制在账本 uploads 目录内。

## 19. 当前开发顺序基线

1. 后端基础：配置、数据库、模型、统一错误、Token 校验。
2. 身份系统：Account、Ledger、Device、AuthToken、UploadLink、PairingCode。
3. Owner Bootstrap：初始化、生成凭证、绑定码管理。
4. 上传闭环：上传图片、保存文件、计算 hash、创建 pending。
5. 账单 API：pending、confirmed 分页、patch、confirm、reject、image。
6. 统计 API：按 `expense_time` fallback `confirmed_at` 统计。
7. Android 绑定与认证：`POST /api/auth/pair`、Keystore、Biometric。
8. Android pending、edit、confirm、reject。
9. Android Room confirmed upsert 和账本离线缓存。
10. README：Windows、Cloudflare Tunnel、iOS 快捷指令、Android Studio。

## 20. 交付清单

当前交付应具备：

- 完整项目结构。
- 后端完整代码。
- Android App 完整代码。
- 数据库模型。
- API 文档。
- Windows 运行说明。
- iPhone 快捷指令配置说明。
- Android Studio 运行说明。
- 安全注意事项。
- OCR、分类规则、重复检测、缩略图、图片清理和生活化统计说明。
- v0.3 身份系统文档（Account、Ledger、Device、凭证管理）。
