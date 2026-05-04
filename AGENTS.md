# 小票夹项目工作规则

本文件是后续 Codex/开发者进入本项目时必须优先读取的项目级规则。

## 必读顺序

开始任何实现前，先阅读：

1. `docs/ENGINEERING_RULES.md`
2. `docs/ARCHITECTURE.md`
3. `docs/PROJECT_STRUCTURE.md`
4. `docs/API.md`
5. `docs/SECURITY.md`
6. `docs/REFERENCES.md`
7. 与当前任务相关的 `docs/DECISIONS/*.md`

后端实现相关任务再阅读：

1. `docs/BACKEND_RULES.md`

Android 实现相关任务再阅读：

1. `docs/ANDROID_RULES.md`

第二版、OCR、分类、重复检测、缩略图、图片清理相关任务再阅读：

1. `docs/V2_ROADMAP.md`

## 阶段约束

默认先按用户当前明确阶段推进。

如果用户只要求后端，只实现 `backend/`。

如果用户明确要求完整软件、Android App、全部版本或端到端闭环，可以进入 `backend/`、`android/` 和 `docs/`。进入 Android 前仍需遵守 `docs/ENGINEERING_RULES.md` 的 Android 分层规则。

## 后端技术栈

- Python 3.11+
- FastAPI
- SQLite
- SQLAlchemy，优先于 SQLModel
- Pydantic
- Uvicorn
- Windows 11 本地运行
- 不使用 Docker
- 不依赖 Linux

## 不允许回退的决定

- 金额必须使用 `amount_cents`，单位为分，不能用 float/double 保存金额。
- 数据库时间保存 UTC，API 返回 ISO 8601 字符串。
- 统计按 `expense_time`，为空时使用 `confirmed_at`。
- uploads 不能作为静态目录公开。
- 图片只能通过 `GET /api/expenses/{id}/image` 鉴权访问。
- API 不返回 Windows 本机真实路径。
- Android 首次绑定以后必须使用 `GET /api/auth/check` 校验 Token，不能用 `/api/health` 代替。
- 统一错误格式必须是 `{"error":"错误代码","message":"中文错误说明"}`。

## 分层边界

后端采用：

```text
routes -> services -> database/models
```

- `routes` 只接收请求、解析参数、调用 service、返回 schema。
- `services` 放业务逻辑、文件处理、统计和状态流转。
- `models` 只定义 SQLAlchemy ORM。
- `schemas` 只定义 Pydantic 请求/响应模型。
- `auth.py` 只处理 Token 校验。
- `errors.py` 只处理统一错误。

不要把 OCR、分类、去重、缩略图、图片清理逻辑写死在 route 中。后续统一从 service/provider 扩展。

## 强制代码质量

本项目强制要求高内聚、低耦合、边界清晰、可插拔、可扩展、可读、可维护。

禁止：

- 过时库。
- 停止维护库。
- alpha/beta 弱依赖进入主线。
- 强耦合代码。
- route / Composable / DAO 中堆业务逻辑。
- 临时凑合的弱代码。

新增依赖、框架或架构变更必须先查官方资料或一手元数据，并把依据写进 `docs/REFERENCES.md` 或相关决策文档。

## Windows UTF-8 规则

- 读取中文文档、README、Markdown、Kotlin、Python、YAML 等文本时，Windows PowerShell 5.1 必须显式使用 `-Encoding UTF8`。
- 禁止用无 `-Encoding UTF8` 的 `Get-Content -Raw` 读取中文文件后再判断内容。
- `.ps1` 文件必须保存为 UTF-8 with BOM，保证 Windows PowerShell 5.1 可直接运行。
- 新增或修改文本文件后运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
```
