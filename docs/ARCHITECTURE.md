# 小票夹完整架构

## 1. 项目定位

小票夹是一个私人半自动记账系统，面向个人使用，不做商业云服务。第一版的核心目标是让账单截图从 iPhone 进入 Windows 后端，再由 Android App 人工确认入账。

第一版重点：

- iPhone 截图上传。
- Windows FastAPI 后端保存截图。
- 后端创建 pending 待确认账单。
- Android App 拉取 pending 账单。
- 用户编辑金额、商家、分类、消费时间、备注。
- 用户确认或拒绝账单。
- confirmed 账单同步到 Android Room 本地缓存。

第一版明确不做：

- 真正 OCR。
- 自动分类。
- 账号注册和登录系统。
- 多用户。
- 邮箱、手机号、第三方登录。
- Web 后台管理页面。
- 复杂图表。
- 远程控制电脑。
- 云端商业部署。
- 自动读取 iPhone 相册。
- 自动入账。
- 微信、支付宝自动监听。
- 银行卡接口。
- 第三方支付接口。

## 2. 总体流程

```text
iPhone 截图
  -> iOS 快捷指令上传图片
  -> https://api.我的域名.com/api/upload-screenshot
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
- Android App 是第一版唯一人工确认入口。
- SQLite 数据库只能被本机后端访问。
- uploads 目录不能被静态公开。
- Cloudflare Tunnel 只映射 API，不映射 Windows 文件夹。

## 3. 后端技术栈

- Python 3.11+
- FastAPI
- SQLite
- SQLAlchemy 或 SQLModel
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
    routes/
      auth.py
      health.py
      expenses.py
      uploads.py
      stats.py
    services/
      file_service.py
      expense_service.py
      time_service.py
  uploads/
  data/
    ticketbox.db
  requirements.txt
  .env.example
  run.bat
  README.md
```

职责划分：

- `main.py`：创建 FastAPI app、注册路由、注册统一异常处理。
- `config.py`：读取 `.env` 或环境变量。
- `database.py`：SQLite engine、session、建表入口。
- `models.py`：数据库 ORM 模型。
- `schemas.py`：Pydantic 请求和响应模型。
- `auth.py`：`Upload-Token` 和 `Authorization: Bearer` 校验。
- `errors.py`：统一错误结构。
- `routes/`：HTTP 层。
- `services/`：业务逻辑和文件处理。

## 4. 后端配置

`.env` 示例：

```env
UPLOAD_TOKEN=替换为随机长字符串
APP_TOKEN=替换为随机长字符串
ADMIN_TOKEN=替换为随机长字符串
DATABASE_URL=sqlite:///data/ticketbox.db
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE_MB=10
DELETE_IMAGE_AFTER_CONFIRM=false
GENERATE_THUMBNAIL=true
DELETE_IMAGE_AFTER_DAYS=0
OCR_PROVIDER=empty
```

`run.bat`：

```bat
@echo off
cd /d %~dp0
call .venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

后端默认只监听：

```text
127.0.0.1:8000
```

不要监听 `0.0.0.0`。

## 5. Token 与权限

使用三个 Token：

```text
UPLOAD_TOKEN  iPhone 快捷指令上传截图使用，只能调用上传接口。
APP_TOKEN     Android App 使用，可读取、编辑、确认、拒绝账单和查看受保护图片。
ADMIN_TOKEN   预留给未来后台管理，第一版可以不实现后台页面。
```

请求头：

```http
Upload-Token: xxxxxx
```

```http
Authorization: Bearer xxxxxx
```

认证规则：

- `/api/upload-screenshot` 只接受 `Upload-Token`。
- Android App 接口只接受 `Authorization: Bearer APP_TOKEN`。
- `/api/auth/check` 必须验证 `APP_TOKEN`。
- `/api/health` 可以不鉴权，只用于本地或隧道健康检查。

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
file_too_large
unsupported_file_type
expense_not_found
amount_required
server_error
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

单位统一为“分”。界面显示时转换为元：

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
amount_cents: int?，金额，单位分
merchant: string?，商家
category: string，默认 其他
note: string?，备注
source: string，默认 iPhone截图
image_path: string?，相对路径
image_hash: string?，图片 sha256，第一版只保存不去重
raw_text: string?，OCR 原文预留
confidence: float?，OCR 置信度预留
status: string，pending / confirmed / rejected
expense_time: datetime?，实际消费时间，UTC
created_at: datetime，上传/创建时间，UTC
updated_at: datetime，更新时间，UTC
confirmed_at: datetime?，确认时间，UTC
rejected_at: datetime?，拒绝时间，UTC
```

分类默认值：

```text
吃饭
数码
生活
交通
游戏
AI订阅
购物
娱乐
医疗
其他
```

状态机：

```text
pending -> confirmed
pending -> rejected
confirmed -> confirmed，允许继续 PATCH 修正
rejected 第一版不恢复、不展示
```

## 10. 图片保存规则

上传图片保存到：

```text
backend/uploads/YYYY/MM/
```

要求：

- 只接受 `jpg`、`jpeg`、`png`、`webp`、`heic`。
- 单个文件最大 10MB。
- 保存前生成随机文件名。
- 不使用原始文件名。
- 计算 `image_hash`，第一版只保存，不强制去重。
- `image_path` 只保存相对路径。
- API 返回不能暴露 Windows 真实路径。
- uploads 不能作为公开静态目录。
- 预留确认后删除原图配置项，第一版默认不自动删除。

iPhone 快捷指令建议上传前转为 JPEG 或 PNG。后端可以接受 HEIC，但第一版不保证 Android 端预览 HEIC。

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
Authorization: Bearer APP_TOKEN
```

返回：

```json
{
  "status": "ok"
}
```

Android 首次绑定服务器时使用这个接口验证 Token。

### 上传截图

```http
POST /api/upload-screenshot
Upload-Token: UPLOAD_TOKEN
Content-Type: multipart/form-data
```

字段：

```text
file: 图片文件
```

行为：

- 校验 `Upload-Token`。
- 校验文件类型。
- 校验文件大小。
- 保存图片到 `uploads/YYYY/MM/`。
- 生成随机文件名。
- 计算 `image_hash`。
- 创建一条 pending expense。
- `amount_cents`、`merchant`、`raw_text` 第一版留空。
- `category` 默认 `其他`。
- `status = pending`。

返回：

```json
{
  "id": 1,
  "status": "pending",
  "message": "uploaded"
}
```

### 获取待确认账单

```http
GET /api/expenses/pending
Authorization: Bearer APP_TOKEN
```

返回：

```json
[
  {
    "id": 1,
    "amount_cents": null,
    "merchant": null,
    "category": "其他",
    "note": "",
    "source": "iPhone截图",
    "image_path": "uploads/2026/05/xxx.png",
    "image_hash": "sha256...",
    "raw_text": "",
    "confidence": null,
    "status": "pending",
    "expense_time": null,
    "created_at": "2026-05-03T12:00:00Z",
    "updated_at": "2026-05-03T12:00:00Z",
    "confirmed_at": null,
    "rejected_at": null
  }
]
```

### 获取已确认账单

```http
GET /api/expenses/confirmed?page=1&page_size=50&month=2026-05&category=吃饭
Authorization: Bearer APP_TOKEN
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
Authorization: Bearer APP_TOKEN
Content-Type: application/json
```

请求体：

```json
{
  "amount_cents": 3680,
  "merchant": "美团外卖",
  "category": "吃饭",
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
Authorization: Bearer APP_TOKEN
```

行为：

- 如果 `amount_cents` 为空，返回 `amount_required`。
- `status` 改为 `confirmed`。
- `confirmed_at` 设置当前 UTC 时间。
- 更新 `updated_at`。

### 拒绝待确认账单

```http
POST /api/expenses/{id}/reject
Authorization: Bearer APP_TOKEN
```

行为：

- `status` 改为 `rejected`。
- `rejected_at` 设置当前 UTC 时间。
- 更新 `updated_at`。

### 获取受保护图片

```http
GET /api/expenses/{id}/image
Authorization: Bearer APP_TOKEN
```

行为：

- 校验 `APP_TOKEN`。
- 查询 expense。
- 根据数据库中的相对 `image_path` 读取本地文件。
- 返回图片流。
- 不返回真实本机路径。
- 不把 uploads 设置成静态目录。

### 本月统计

```http
GET /api/stats/monthly?month=2026-05
Authorization: Bearer APP_TOKEN
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
      "category": "吃饭",
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
- Retrofit 或 Ktor Client
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
          LoginScreen.kt
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
  -> Retrofit/Ktor API + Room DAO
  -> UI State
```

## 13. Android 绑定与登录

第一版不做账号密码。

首次打开：

```text
绑定我的服务器
  -> 输入服务器地址，例如 https://api.我的域名.com
  -> 输入 App Token
  -> 调用 GET /api/auth/check
  -> 成功后保存服务器地址
  -> App Token 存入 Android Keystore
  -> 进入 App
```

后续打开：

```text
显示 小票夹
  -> 弹出指纹/面容验证
  -> 验证成功后读取 Keystore 中的 Token
  -> 进入主界面
```

安全要求：

- 指纹只用于解锁本地 Token。
- 服务器仍然通过 `Authorization: Bearer APP_TOKEN` 校验。
- App 切到后台超过 5 分钟，再回来需要重新验证。
- 设置页提供“清除绑定”。

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
- 每条显示截图缩略图或“截图已上传”。
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
OCR 原文，第一版为空，可折叠
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

第一版统计：

```text
本月总支出
本月账单数量
各分类支出
最大一笔支出
最近 7 天支出
```

第一版可以使用 Compose 简单卡片或列表，不强制复杂图表。

### 设置页

功能：

```text
显示当前服务器地址
测试连接
重新同步
清除本地缓存
清除服务器绑定
修改分类列表，第一版可选
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
- `serverId` 必须唯一。
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
  -> multipart/form-data
  -> 字段名 file
  -> 添加 Upload-Token 请求头
  -> 成功后显示 已上传到小票夹
```

URL：

```text
https://api.我的域名.com/api/upload-screenshot
```

请求头：

```http
Upload-Token: xxxxxx
```

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
- 受保护图片接口必须验证 `APP_TOKEN`。
- 预留确认后删除原图配置项。

## 19. 第一版开发顺序

1. 后端基础：配置、数据库、模型、统一错误、Token 校验。
2. 上传闭环：上传图片、保存文件、计算 hash、创建 pending。
3. 账单 API：pending、confirmed 分页、patch、confirm、reject、image。
4. 统计 API：按 `expense_time` fallback `confirmed_at` 统计。
5. Android 绑定与认证：`/api/auth/check`、Keystore、Biometric。
6. Android pending、edit、confirm、reject。
7. Android Room confirmed upsert 和账本离线缓存。
8. README：Windows、Cloudflare Tunnel、iOS 快捷指令、Android Studio。

## 20. 交付清单

第一版完成时应具备：

- 完整项目结构。
- 后端完整代码。
- Android App 完整代码。
- 数据库模型。
- API 文档。
- Windows 运行说明。
- iPhone 快捷指令配置说明。
- Android Studio 运行说明。
- 安全注意事项。
- 后续 OCR 升级建议。
