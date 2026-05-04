# 小票夹工程规范

## 1. 总原则

小票夹第一版以稳定闭环为最高优先级。

优先级：

1. 数据正确。
2. 安全边界清楚。
3. 能在 Windows 11 本地运行。
4. Android 后续能稳定确认入账。
5. 代码可维护。
6. UI 美观。
7. 扩展能力。

第一版不追求复杂架构，不引入不必要的大型框架。

## 2. 阶段约束

默认先按用户当前明确阶段推进。

如果用户只要求后端，只实现 `backend/`。

如果用户明确要求完整软件、Android App、全部版本或端到端闭环，可以进入 `backend/`、`android/` 和 `docs/`。进入 Android 前仍需遵守本文档的 Android 分层规则。

## 3. 后端分层规范

后端采用轻量分层：

```text
routes -> services -> database/models
```

第一版可以不强制拆 repository/provider，但必须保证边界清楚。

### routes 层

职责：

- 接收 HTTP 请求。
- 解析参数。
- 调用 Token 校验。
- 调用 service。
- 返回 Pydantic schema。

禁止：

- 直接写复杂业务逻辑。
- 直接拼复杂 SQL。
- 直接操作真实文件路径。
- 直接返回 Python exception。
- 直接返回 Windows 本机路径。

### services 层

职责：

- 业务流程编排。
- 文件保存。
- 创建 pending。
- 修改账单。
- 确认账单。
- 拒绝账单。
- 统计计算。
- 图片读取。
- hash 计算。

禁止：

- 依赖 FastAPI Request。
- 直接返回 HTTP Response。
- 写 UI 文案。
- 硬编码真实 Token。

### models 层

职责：

- SQLAlchemy ORM 模型。
- 数据库字段定义。

禁止：

- 依赖 routes。
- 依赖 schemas。
- 依赖 HTTP 层。

### schemas 层

职责：

- Pydantic 请求模型。
- Pydantic 响应模型。

禁止：

- 放数据库连接逻辑。
- 放业务流程。
- 放文件操作。

## 4. 后端扩展规范

第一版先实现最小服务，但必须为第二版预留扩展点。

未来功能不要写死在 route 中：

- OCR。
- 自动分类。
- 重复检测。
- 缩略图。
- HEIC 转 JPEG。
- 图片清理策略。

推荐未来扩展方向：

```text
services/
  ocr_service.py
  classify_service.py
  duplicate_service.py
  thumb_service.py
  cleanup_service.py
```

第一版原则：

```text
可以先不创建复杂 provider
但不要把 OCR / 分类 / 去重 / 缩略图逻辑写死在 uploads.py
```

## 4.1 强代码硬规则

以下规则是强制要求：

- 高内聚、低耦合。
- 边界清晰，禁止跨层乱调。
- 可插拔扩展，禁止把未来 OCR、分类、去重、缩略图、清理策略写死。
- 代码要可读、可维护、可测试。
- 结构要清晰，架构意图要能从目录和命名看出来。
- 依赖必须来自可靠、活跃、官方推荐或事实标准生态。
- 禁止过时库、停止维护库、alpha/beta 弱依赖进入主线。
- 禁止为了赶进度写强耦合、弱抽象、难测试的代码。
- 禁止 UI 层、route 层、数据库层互相穿透。
- 关键技术决策必须写进 `docs/DECISIONS/`。
- 新增依赖必须先查 `docs/REFERENCES.md` 所列官方文档或 Maven/包管理元数据。

允许：

- 第一版保持轻量。
- 为第二版保留清楚扩展点。
- 先用简单实现，但实现必须可替换。

不允许：

- 先凑合写死，后面再说。
- 在 route 或 Composable 里堆业务逻辑。
- 把基础设施细节泄露到 UI。
- 用过时依赖或不稳定依赖冒充现代化。

## 5. 金额规范

全链路统一使用：

```text
amount_cents
```

单位是分。

后端：

```python
amount_cents: int | None
```

Android：

```kotlin
amountCents: Long?
```

禁止：

```text
amount: float
amount: double
数据库保存元
用浮点数保存金额
```

UI 显示时才转换为元。

示例：

```text
3680 -> ¥36.80
```

金额转换必须集中封装，不允许每个页面手写除以 100。

## 6. 时间规范

数据库保存 UTC 时间。

API 返回 ISO 8601 字符串。

字段含义：

```text
created_at      上传/创建时间
updated_at      更新时间
expense_time    实际消费时间
confirmed_at    确认入账时间
rejected_at     拒绝时间
```

统计口径：

```text
优先 expense_time
如果为空，使用 confirmed_at
```

Android 显示时转本地时间。

禁止：

- 用 `created_at` 当消费时间。
- Android 伪造 `confirmed_at`。
- 后端按 Android 本地时区格式化显示。

## 7. 错误返回规范

所有错误统一格式：

```json
{
  "error": "错误代码",
  "message": "中文错误说明"
}
```

固定错误码：

```text
invalid_token
file_too_large
unsupported_file_type
expense_not_found
amount_required
server_error
```

禁止：

- 返回 traceback。
- 返回英文底层异常。
- 每个接口自定义不同错误结构。
- 吞异常后返回成功。

## 8. 图片安全规范

uploads 目录绝对不能公开。

禁止：

```text
StaticFiles 暴露 uploads
API 返回 C:\xxx\xxx.png
API 返回 E:\projects\xxx
使用原始文件名保存
```

允许：

```text
数据库保存相对路径
图片通过 /api/expenses/{id}/image 鉴权读取
```

图片接口必须校验：

```text
Authorization: Bearer APP_TOKEN
```

图片清理只能通过窄维护接口按配置执行：

```text
POST /api/maintenance/cleanup-images
Authorization: Bearer ADMIN_TOKEN
```

禁止维护接口接收任意路径或提供通用文件管理能力。

## 9. 后端配置规范

后端配置统一从 `config.py` 读取。

配置项：

```text
UPLOAD_TOKEN
APP_TOKEN
ADMIN_TOKEN
DATABASE_URL
UPLOAD_DIR
MAX_UPLOAD_SIZE_MB
DELETE_IMAGE_AFTER_CONFIRM
GENERATE_THUMBNAIL
DELETE_IMAGE_AFTER_DAYS
OCR_PROVIDER
```

禁止业务代码到处读取 `os.environ`。

禁止真实 Token 写入：

```text
代码
README
Git
截图
日志
```

## 9.1 Windows UTF-8 规范

小票夹后端脚本面向 Windows 11 和 Windows PowerShell 5.1。

规则：

```text
backend/scripts/*.ps1 使用 UTF-8 with BOM
backend/.env 使用 UTF-8 without BOM
README 和 docs 使用 UTF-8
脚本必须能被 powershell.exe -File 直接运行
不要求 PowerShell 7、WSL、Docker 或 Linux shell
```

原因：

```text
Windows PowerShell 5.1 对无 BOM 的 UTF-8 脚本可能按 ANSI 解析。
包含中文输出的脚本如果无 BOM，可能乱码或解析失败。
```

读取规则：

```powershell
Get-Content -Raw -Encoding UTF8 README.md
Get-Content -Raw -Encoding UTF8 docs\ENGINEERING_RULES.md
```

禁止：

```powershell
Get-Content -Raw README.md
Get-Content -Raw docs\ENGINEERING_RULES.md
```

原因是 Windows PowerShell 5.1 在无 BOM 文件上可能按系统 ANSI 代码页读取，中文会显示为常见 UTF-8/ANSI 误读乱码。文件本身可以是 UTF-8，但读取命令必须显式声明编码。

验收：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
```

## 10. 网络与认证规范

上传截图只使用：

```http
Upload-Token: UPLOAD_TOKEN
```

App 接口只使用：

```http
Authorization: Bearer APP_TOKEN
```

绑定服务器以后只用：

```http
GET /api/auth/check
```

不要用 `/api/health` 判断 Token 是否正确。

图片只通过：

```http
GET /api/expenses/{id}/image
```

禁止客户端直接访问 uploads 路径。

## 11. 统计规范

统计主口径以后端为准。

后端统计：

```text
只统计 confirmed
按 COALESCE(expense_time, confirmed_at)
金额使用 amount_cents
```

Android 后续可以做本地离线展示，但不要和后端统计口径冲突。

## 12. Android 分层规范

Android 后续使用轻量 MVVM：

```text
Screen -> ViewModel -> Repository -> ApiService / Dao / TokenStore
```

### Screen

职责：

- 展示 UI。
- 收集用户输入。
- 触发 ViewModel 事件。

禁止：

- 直接调用 Retrofit。
- 直接调用 Room。
- 直接读写 SharedPreferences。
- 直接保存 Token。
- 写复杂业务逻辑。

### ViewModel

职责：

- 管理页面状态。
- 调用 Repository。
- 处理加载中、成功、失败。
- 暴露 UI State。

禁止：

- 创建 Retrofit。
- 创建 Room Database。
- 持有 Activity。
- 直接操作 Keystore 加密细节。

### Repository

职责：

- 协调远程 API 和本地 Room。
- 负责同步 confirmed。
- 负责失败 fallback 到本地缓存。

禁止：

- 写 Compose 状态。
- 写 UI 控件逻辑。
- 返回 DTO 给 UI。

### DAO

职责：

- Room 查询。
- Room upsert。
- Room 删除。

禁止：

- 返回 DTO。
- 调用网络。
- 处理 Token。

## 13. Android 数据模型规范

三类模型必须分开：

```text
DTO      服务端接口模型
Entity   Room 本地模型
Domain   App 内业务模型
```

命名：

```text
ExpenseDto
ExpenseEntity
Expense
ExpenseDraft
ExpenseUpdateRequest
```

转换集中放在：

```text
ExpenseMappers.kt
```

禁止：

- UI 直接使用 DTO。
- UI 直接使用 Entity。
- DTO 带 Room 注解。
- Entity 带 Moshi 网络注解。
- Domain 依赖 Android Context。

## 14. Room 规范

`serverId` 必须唯一。

confirmed 同步必须使用 upsert。

规则：

```text
如果 serverId 已存在，更新本地记录
如果 serverId 不存在，插入本地记录
不允许重复插入
```

confirmed 必须缓存。

pending 第一版可以不缓存。

默认排序：

```sql
ORDER BY COALESCE(expenseTime, confirmedAt, createdAt) DESC
```

## 15. Token 与客户端安全规范

APP_TOKEN：

- 不写死在代码里。
- 不打印到日志。
- 不明文存 SharedPreferences。
- 使用 Android Keystore 保存。

BiometricPrompt：

- 只用于本地解锁。
- 不替代服务端 Token 校验。

清除绑定必须清除：

```text
serverUrl
APP_TOKEN
本地解锁状态
可选：本地缓存
```

OkHttp 日志：

```text
Debug 最多 BASIC
不得打印 Header
不得打印 Body
不得打印 Token
```

## 15.1 Android 依赖规范

Android 插件和库版本统一维护在：

```text
android/gradle/libs.versions.toml
```

规则：

- `android/build.gradle.kts` 只通过 `libs.plugins.*` 引用插件。
- `android/app/build.gradle.kts` 只通过 `libs.*` 引用 Android 第三方依赖。
- 新增 Android 依赖时先写入 Version Catalog，再在模块中引用。
- 不在模块 `build.gradle.kts` 中散写版本号。
- 不引入 alpha、beta、停止维护或来源不清的依赖进入主线。
- 升级依赖必须跑 `:app:testDebugUnitTest`、`:app:assembleDebug` 和 `:app:lintDebug`。

## 16. UI 规范

整体风格：

```text
中文
深色优先
Material 3
卡片式
圆角
生活化
不要后台管理风
```

金额为空：

```text
待填写金额
```

商家为空：

```text
未填写商家
```

HEIC 无法预览：

```text
截图已保存，当前格式暂不预览
```

网络失败：

```text
显示中文错误
账本页展示本地缓存
不要白屏
```

## 17. 实机联调规范

实机联调必须同时覆盖：

```text
iPhone 快捷指令上传
Cloudflare Tunnel 公网域名
Windows FastAPI 后端
Android 真机绑定和自检
pending 编辑确认
Room confirmed 缓存
统计页刷新
```

联调脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\real_device_preflight.ps1
```

约束：

- 预检脚本不得打印 `UPLOAD_TOKEN`、`APP_TOKEN` 或 `ADMIN_TOKEN`。
- 测试上传只能使用脚本内置小图或用户明确指定的受控文件，不做通用文件管理能力。
- 设备安装逻辑复用 `android\scripts\install_debug_apk.ps1`。
- 真机联调仍然不能公开 `uploads/`。
- 真机联调仍然不能把后端监听地址改成 `0.0.0.0`。
- Cloudflare Tunnel 只映射到 `http://127.0.0.1:8000`。

## 18. Git 提交规范

推荐提交粒度：

```text
init backend skeleton
implement auth and errors
implement upload screenshot
implement pending expenses
implement confirm reject
implement protected image endpoint
implement confirmed pagination
implement monthly stats
init android skeleton
implement server binding
implement biometric unlock
implement pending screen
implement edit screen
implement room cache
implement settings screen
```

禁止：

```text
一个 commit 混合大改后端、Android、文档、UI
一个 commit 同时做多个无关功能
测试没跑就提交
```

## 19. 后端验收清单

每次后端阶段完成必须能测试：

```text
GET /api/health
GET /api/auth/check 正确 Token
GET /api/auth/check 错误 Token
POST /api/upload-screenshot
上传超大文件
上传不支持格式
GET /api/expenses/pending
PATCH /api/expenses/{id}
POST /api/expenses/{id}/confirm
amount_cents 为空时 confirm 报 amount_required
POST /api/expenses/{id}/reject
GET /api/expenses/confirmed?page=1&page_size=50
GET /api/expenses/{id}/image 正确 Token
GET /api/expenses/{id}/image 错误 Token
GET /api/stats/monthly
```

自动化命令：

```bat
.venv\Scripts\python.exe -m compileall app scripts tests
.venv\Scripts\ruff.exe check app scripts tests
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe scripts\smoke_test.py
```

## 20. Android 验收清单

每次 Android 阶段完成必须验证：

```text
Gradle Sync 通过
App 能启动
绑定服务器页可用
Token 正确绑定成功
Token 错误显示中文错误
生物识别可用
待确认列表能加载
编辑页能保存
金额元转分正确
确认入账成功
确认后 Room upsert
重复同步不重复插入
账本页能显示本地缓存
断网后账本页不白屏
设置页能测试连接
设置页能清除绑定
```

自动化命令：

```powershell
.\gradlew.bat --no-daemon :app:testDebugUnitTest
.\gradlew.bat --no-daemon :app:assembleDebug
.\gradlew.bat --no-daemon :app:lintDebug
```

## 21. 文档规范

docs 目录建议：

```text
docs/
  ARCHITECTURE.md
  PROJECT_STRUCTURE.md
  API.md
  SECURITY.md
  ENGINEERING_RULES.md
  BACKEND_RULES.md
  ANDROID_RULES.md
  V2_ROADMAP.md
  DECISIONS/
    0001-money-uses-cents.md
    0002-expense-time-vs-created-at.md
    0003-uploads-not-public.md
    0004-room-serverid-upsert.md
```

关键决策必须写入 `docs/DECISIONS/`。

## 22. 扩展性原则

小票夹采用：

```text
接口化，不平台化
可替换，不动态加载
边界清楚，不复杂分层
```

第一版不做复杂 provider 系统，但代码必须允许未来扩展：

```text
OCR
自动分类
重复检测
缩略图
图片清理
生活化统计
Web 管理端
```

未来扩展不应破坏第一版核心闭环。

## 23. 不允许回退的决定

后续开发不得改回：

```text
amount: float
amount: Double?
公开 uploads
用 /api/health 验证 Token
API 返回 Windows 真实路径
Android 直接访问 uploads
UI 直接调 Retrofit
UI 直接调 Room
Android 自己生成 confirmed_at
confirmed 同步重复插入
错误格式不统一
```
