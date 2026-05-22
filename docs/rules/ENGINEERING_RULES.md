# 工程规范

> 通用部分采用模板 v1.2.1（2026-05-22）；后端 + 客户端协作项目契约。
> 任何放宽必须写入 `docs/DECISIONS/`，注明原因、风险、偿还计划和回收条件。
> 小票夹项目独有补充见 §14。

---

## 0. 裁决顺序

冲突时按以下优先级判断：

1. 数据正确
2. 安全边界清晰
3. 目标环境稳定运行
4. 端到端闭环稳定
5. 可维护、可测试
6. 用户体验
7. 扩展能力
8. UI 表现

架构可以简单，但边界必须清楚；实现可以先小，但必须可替换、可回滚、可验证。

---

## 1. 分层架构

### 后端

固定分层：`routes → services → models / providers`

* `routes`：参数解析、鉴权、调用 service、返回 schema；不写业务、不拼复杂 SQL、不返回原始异常。
* `services`：业务编排、事务、调用 provider；不依赖 HTTP 层、不写 UI 文案、不硬编码凭证。
* `models`：ORM 实体；不依赖上层。
* `schemas`：请求/响应结构；不放业务、不放 IO。
* `providers`：OCR、分类、推送、外部 LLM 等可替换能力；只做识别或建议，不直接确认业务状态。

### 客户端

固定分层：`Screen → ViewModel → Repository → ApiService / Dao / SecureStorage`

* `Screen`：只做 UI 渲染和输入收集。
* `ViewModel`：管理 UI State，调用 Repository。
* `Repository`：协调远端、本地缓存、失败兜底，返回领域模型。
* `ApiService / Dao / SecureStorage`：纯 IO 层，不向 UI 暴露 DTO / Entity / Token。

### 禁忌

禁止跨级调用、DTO/Entity 进 UI、UI 直连网络、route 直查 DB。
三类模型必须分开：`XxxDto / XxxEntity / Xxx`，转换集中在 `XxxMapper`。
任何快捷方案必须写入 `DECISIONS/`，标注偿还计划。

---

## 2. 项目结构

目标：从目录就能看出架构意图，新人不读文档也能猜对一类文件该放哪。

### 顶层目录

```
project-root/
├── README.md            启动方式 + 最小说明
├── LICENSE
├── .gitignore
├── .env.example         配置模板，禁止真实凭证
├── docs/                所有文档
├── scripts/             运维、构建、检查脚本，禁止业务代码
├── backend/             服务端代码
├── client/              客户端代码（多端时再切子目录）
└── tests/               跨端集成测试（可选）
```

根目录禁止：散文件、个人笔记、tmp、backup、v2、old。

### 后端目录

```
backend/
├── app/
│   ├── routes/
│   ├── services/
│   ├── models/
│   ├── schemas/
│   ├── providers/
│   ├── config.py / config/       统一配置入口
│   └── main.py / entrypoints/    启动入口
├── tests/
├── migrations/          数据库迁移
├── scripts/             后端专用脚本
└── 依赖清单文件
```

后端启动与配置入口必须明确命名，例如 `config.py / config/`、`main.py / entrypoints/`；禁止使用含糊目录名让实现者自行猜测。

### 客户端目录

按"层"组织，业务在层内分子目录，不按"页面"切顶层目录：

大型项目允许按 feature / module 分组，但层边界不得打穿；模块化不是跨层调用的理由。

```
client/
├── ui/{module_a, module_b, ...}/
├── viewmodel/{module_a, module_b, ...}/
├── repository/
├── data/{api, db, storage}/
├── domain/
├── di/
└── util/
```

### 文档目录

```
docs/
├── PROJECT_BOUNDARY.md
├── API.md
├── ACCEPTANCE.md
├── RUNBOOK.md
├── ENGINEERING_RULES.md
├── DECISIONS/
└── assets/              图片、附件
```

### 运行时产物

`uploads/  data/  logs/  build/  dist/  本地虚拟环境  依赖缓存目录` 全部进 `.gitignore`，路径走 config，不写死。

### 命名约定

* 目录、文件、字段、API 路径：小写下划线
* 类、类型：大驼峰
* 常量、环境变量：大写下划线
* 关键规范文档：大写下划线 `.md`
* 普通文档：小写连字符 `.md`

### 禁忌

* 不在根目录散放代码、文档、图片
* 不留 `v1/ v2/ old/ backup/ tmp/` 残留
* 不让 git 跟踪运行时产物
* 不让业务代码进 `scripts/`
* 不让二进制文件散落在 `docs/` 根部（统一放 `docs/assets/`）

---

## 3. 数据规范

### 标识

外部实体同时维护：

* `id`：内部主键，用于本系统路径和关联。
* `public_id`：UUID，用于跨端同步、导出、追溯、未来合并。

普通 UI 不暴露任何 id。

### 金额

* 金额全链路使用最小货币单位整数，如 `amount_cents: int`。
* 禁止用 `float / double` 保存金额。
* 多币种使用：`original_currency_code + original_amount_minor + exchange_rate_*`。
* 统计只汇总基准币种，禁止跨币种直接相加。
* 单位换算集中封装，禁止 UI 散写 `÷100`。

### 时间

* 存储：UTC。
* API：ISO 8601。
* 字段固定：`created_at / updated_at / event_time / confirmed_at / rejected_at`。
* 统计口径：`COALESCE(event_time, confirmed_at)`。
* 客户端负责本地时区显示，后端不按客户端时区格式化。

### 幂等

所有写操作必须支持 `client_request_id`。
重试不得产生重复业务记录。

---

## 4. 接口规范

* API 必须有版本策略，如 `/api/v1/...`。
* 破坏性变更（删字段、改类型、改语义）必须 bump 大版本，并保留旧版本兼容期。
* 请求/响应字段命名固定，不随 UI 文案变化。
* 分页统一：`page / page_size / total / items`。
* 排序、过滤字段必须白名单化。
* API 不返回服务器本机路径、内部 URL、堆栈信息。

统一错误格式：

```json
{ "error": "错误代码", "message": "中文说明" }
```

通用错误码：

`invalid_token / invalid_request / not_found / method_not_allowed / file_too_large / unsupported_file_type / amount_required / state_conflict / rate_limited / server_error`

禁止返回 traceback、英文底层异常、接口各自发明错误结构、吞异常返回成功。

---

## 5. 鉴权、安全与发布面

* 服务端 Token / Session 是最终鉴权来源。
* 客户端生物识别只解锁本地状态，不替代服务端鉴权。
* Token 不写代码、不进日志、不进 README、不进截图、不进 git。
* 客户端凭证必须进入系统级安全存储（Keystore / Keychain 等）。
* 上传目录禁止公开挂载，文件只能通过鉴权接口访问。
* API 不返回本机文件路径。

构建分级：

| 构建            | 用途   | 诊断入口         | 日志输出上限     |
| ------------- | ---- | ------------ | ---------- |
| dev/debug     | 本机开发 | 全开           | DEBUG+     |
| gray/internal | 内测   | 简化，仅连接状态/版本号 | INFO+，禁 Header/Body |
| release       | 公开发行 | 全关           | WARN+      |

诊断入口必须编译期裁掉，不能只靠运行时隐藏。
维护接口必须独立 admin 鉴权，只暴露窄能力，禁止任意路径、任意 SQL、通用文件管理。

---

## 6. 持久化、同步与恢复

* 后端 schema 变更必须走迁移工具，附可执行回滚。
* 客户端 schema 变更必须提交 schema 描述文件和显式迁移策略。
* 新增非空列按三步走：先可空/默认值 → 数据回填 → 收紧约束。
* 服务端是业务真源，客户端本地库只是缓存。
* 同步使用 upsert，唯一键必须叠加隔离键，如 `(tenant_id, server_id)`。
* 隔离由服务端 `tenant_id / scope_id` 实现，禁止靠前端过滤代替隔离。
* 数据库和文件存储都必须备份。
* 每个版本至少做一次恢复演练；没演练的备份等于没有备份。

---

## 7. 状态、事务、并发与任务

* 核心业务状态必须写成有限状态机，不靠散落 if 判断。
* 状态流转必须校验当前状态，冲突返回 `state_conflict`。
* 一个业务动作涉及多表时必须使用事务。
* 并发写入必须有唯一约束、锁或版本号保护。
* 后台任务必须可重试、可停止、可观测，不得悄悄吞错。
* 客户端重试使用指数退避 + jitter，且必须有终止条件。

---

## 8. Provider、配置与自动化

OCR、分类、推送、支付、外部 LLM 等必须 provider 化：

* 有显式接口契约。
* 至少有 empty / mock 实现。
* 通过配置切换。
* 失败不得破坏主业务闭环。

业务代码统一从 config 模块读取配置，禁止散写环境变量取值。
模型名、服务地址、阈值、开关不写死在业务代码里。
自动识别、自动填充、AI 建议只能填空字段，不得覆盖用户手动编辑值。
AI/OCR/LLM 结果默认是"建议"，不是事实。

---

## 9. 依赖治理

* 版本集中管理：依赖清单、版本目录或锁文件统一维护。
* 禁止 alpha、beta、停止维护、来源不清依赖进入主线。
* 新增依赖前查官方文档、维护状态、许可证。
* 结论写入 `DECISIONS/`。
* 升级依赖必须跑：单测、关键构建、lint、依赖审计。

---

## 10. 用户面与文案

普通用户界面不得出现：服务器域名、Token、接口名、端口、DNS、TLS、Tunnel、日志路径、诊断脚本名。

错误文案像生活 App：

* 正确：`连接不上服务器，请稍后再试`
* 错误：`DNS resolve failed for xxx.example.com:8000`

技术原因写日志，或放在内测构建连接详情页。
UI 字符串必须走资源文件，预留 i18n 通道。

---

## 11. 测试、发布与回滚

本规范必须配套 `scripts/verify.*` 检查脚本；没有可执行检查的规范，只算文档，不算工程约束。

发布前必须全部通过：

* 单元测试
* 关键集成测试
* API 契约测试
* lint / 静态检查
* 依赖审计
* 数据库迁移和回滚演练
* 备份恢复演练
* release 无诊断入口、真实凭证、本机路径、内部 URL
* API 契约与客户端 DTO 已对齐
* 验收清单全部勾选

任一项不过，不发。

每次发布必须有回滚方案：代码怎么回滚，数据库怎么兼容，旧客户端是否可用，文件存储是否受影响。

---

## 12. 可观测性与运维

* `/health/liveness`：进程活着即返回 200，不查依赖。
* `/health/readiness`：能服务请求才返回 200，检查 DB 和关键 provider。
* 日志级别 `DEBUG / INFO / WARN / ERROR`：代码按 INFO 写，输出上限由构建决定（见 §5）。
* 敏感字段必须脱敏。
* 错误日志必须带 `request_id / trace_id`。
* 安全和数据修改动作必须记录审计日志。
* 项目必须有最低性能预算：上传大小、API 超时、分页上限、缓存容量、后台任务并发、日志保留天数。
* 禁止无上限上传、无上限查询、无上限缓存、无上限后台任务。

---

## 13. 流程、文档与反扩

项目至少维护：

* `README.md`：启动方式和最小说明。
* `docs/PROJECT_BOUNDARY.md`：项目边界——做什么、不做什么、对接什么、不对接什么。
* `docs/API.md`：接口契约。
* `docs/DECISIONS/`：决策记录。
* `docs/ACCEPTANCE.md`：验收清单。
* `docs/RUNBOOK.md`：部署、备份、恢复、故障处理。

PR Review 必看：分层、目录归位、数据真源、依赖、凭证、迁移、幂等、API 对齐、release 面。

不做以下事情：

* 不为"以后可能用得上"提前引入大框架。
* 不用工作流引擎解决几个 if 能解决的问题。
* 不把 UI、业务、基础设施搅进一个文件里。
* 不在 release 留工程师彩蛋、后门、隐藏入口。
* 不靠前端隐藏代替后端鉴权。
* 不靠"大家都遵守"代替编译期约束、测试和契约检查。
* 不在主线引入未经验证的大版本升级。
* 不让 AI/OCR/LLM 自动结果直接改写用户确认过的数据。

---

## 14. 小票夹项目特定补充

以下是通用模板未覆盖、本项目独有的约束。

### 身份模型（identity_schema=v0.3，冻结）

`Account / Ledger / LedgerMember / Device / AuthToken / UploadLink / PairingCode / Invitation / LedgerAuditLog`（详见 `docs/architecture/ACCOUNT_SYSTEM.md`）。

* `tenant_id` 字段在 v0.3 起语义等同 `ledger_id`。
* 角色：`owner / member / viewer`；viewer 写入必须后端 403，前端隐藏只做体验。
* 邀请 `Invitation.role` 只接受 `member / viewer`；owner 通过显式 owner-transfer。

### OCR / receipt parse provider

* Provider 命名：`empty`（默认空）、`mock`（测试）、`rapidocr`（本地图片）、`local_llm`（OpenAI 兼容视觉模型）。
* 自动 OCR 由 `OCR_AUTO_RUN` 控制，默认关；provider 失败不破坏 pending 创建。
* 提取入口在 `backend/app/services/receipt_parse_service.py`；金额、商家、时间、分类候选拆到 `receipt_parse_amount.py / _merchant.py / _time.py / _category.py`，禁止散到 route 或 Android UI。

### 暴露面与边界

* 公网（Cloudflare Tunnel）仅暴露 `/api/*` 和 `/u/{upload_key}`。
* `/owner` 和 `/web` 强制 loopback（127.0.0.1 + Host 头双检，见 `backend/app/network_boundary.py`）。
* `/api/admin/*` 默认 loopback；`ALLOW_PUBLIC_ADMIN_API=true` 才放开（不建议）。
* `uploads/` 永不 mount 为静态资源；图片只通过 `GET /api/expenses/{id}/image` 鉴权读取。

### iPhone UploadLink

* 唯一入口：`POST /u/<upload_key>?tz=Asia/Shanghai`。
* UploadLink 凭证 scope 受限：只能创建 pending，不能读账本/确认/导出/统计/读图片。

### Upload path 解析单一入口

* 任何 DB 里的 `image_path / thumbnail_path` 还原到 `Path`，必须走 `app.services.file_service.resolve_upload_path_for_tenant`。
* 禁止手写 `BACKEND_ROOT / relative_path` 或 `settings.upload_dir / relative_path`：外部绝对 upload_dir 配置下会指向错误位置且绕过 path-traversal 防护。

### Auth check ≠ health

* 客户端绑定后用 `GET /api/auth/check` 验证 token；不要用 `/api/health` 判断。

### Windows PowerShell 5.1 + UTF-8 BOM

* `backend/scripts/*.ps1` 和 `scripts/*.ps1` 必须 UTF-8 with BOM；`.env` 不带 BOM。
* PS 脚本读文件必须显式 `Get-Content -Encoding UTF8`（PS 5.1 无 BOM UTF-8 默认按 ANSI 解析，中文乱码）。
* PS 脚本不能用 `&&` / `||` 链接（5.1 语法错），用 `; if ($?) { ... }`。
* `scripts/check_text_encoding.ps1` 在 CI / verify 都跑，违反就 fail。
* 不依赖 PowerShell 7、WSL、Docker 或 Linux shell。

### 三端视觉同步

Android / `/web` / `/owner` 共享一套 design tokens（`backend/app/static/shared/tokens.css` + Android `ui/design/`）。改一处颜色/间距/copy 时其它两端同步改，不接受端内分叉。

### 外部产品参考边界

Monarch、支付宝账单等外部产品只允许作为**体验模式**参考；不得照搬 UI 布局、素材、商标、专有文案（详见 `docs/roadmap/MONARCH_INSPIRED_UI.md`）。

### 代码质量数字门槛

详见 [CODE_QUALITY_STANDARDS.md](CODE_QUALITY_STANDARDS.md)：ruff 规则集、line-length、McCabe 复杂度、detekt 默认门槛、PR size、Conventional Commits。

### 依赖与错误码查询

* 依赖管理细则与升级流程：[DEPENDENCIES.md](DEPENDENCIES.md)
* 错误码 → UI 文案映射：[ERROR_MESSAGE_MAPPING.md](ERROR_MESSAGE_MAPPING.md)
* 官方文档与依赖来源：[REFERENCES.md](REFERENCES.md)

---

## 附：变更管理

遵循语义化版本：`MAJOR.MINOR.PATCH`。

* `MAJOR`：改变工程边界。
* `MINOR`：增加规则。
* `PATCH`：修正措辞或格式。

每次变更必须写明日期、摘要、影响范围。
规则放宽必须进入 `docs/DECISIONS/`，并写明回收条件。
