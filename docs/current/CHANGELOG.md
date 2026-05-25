# Changelog

所有版本都保持 `identity_schema=v0.3` 不变。

## v1.2.0 — Learning Feedback Dual Tables + OCR facts 单源（当前）

- Learning Feedback 三张 append-only 表（ADR-0037）：`algorithm_decisions`（决策事实 append-only，治理状态可流转 active/superseded/withdrawn）/ `ledger_learning_events`（用户反馈 append-only）/ `ocr_facts`（OCR 抽取事实 append-only，与 expenses 1:N）；tenant_id 强制隔离；retention_days + `cleanup_expired_learning_tables`
- Learning service ops 收口：`signal_hash` 信号幂等键、cleanup 接调度入口、lifecycle closing、retention split（决策 / 反馈 / OCR 各自 retention）、scheduler、manual dismiss、accept 路径关单
- `_count_recent_rejects` 反馈降权：分类建议 / 重复评分在 N 天内被 reject 后自动降权
- 算法版本回滚：`withdraw_algorithm_version` 把整个 `(decision_type, algorithm_version)` 翻成 `withdrawn`；tenant 隔离
- Algorithm registry：`CATEGORY_SUGGESTION` / `DUPLICATE_CANDIDATE` / `BUDGET_SUGGESTION` 三类决策收拢到 `learning_service._algorithm_registry`，service 端 `ALGORITHM_VERSION` 从 registry 取
- OCR facts 单源迁移 5/5 步骤：
  - Step 1: `latest_for_expense` + `read_ocr_text` 单源 helper
  - Step 2: rule classifiers 改走 `read_ocr_text`
  - Step 3: backfill `expense.raw_text` → `ocr_facts.raw_text`（兼容 pre-alembic）
  - Step 4: read 路径 drop `expense.raw_text` fallback
  - Step 5: 业务逻辑彻底不再读 `raw_text`
- OCR retry 行为修复：空 OCR retry 不再覆盖已有有意义文本；`/api/expenses/{id}/recognize-text` 强制 fact-backed 响应
- Maintenance scope 修复：`learning-status` / `cleanup-learning` 收到当前 admin 的 tenant
- ADR-0037 PR 124 review edge cases 收紧
- ADR-0037 append-only 措辞与 Bad list 在文档层更新

## v1.1 — 跳号

- 未发布。ADR-0036 (v1.1 AI Budget Provider Privacy Boundary) 已 codify——明示 AI provider 可见的字段子集 + 本地保留映射表 + `EmptyBudgetAdvisor` / `OpenAiCompatBudgetAdvisor` provider 抽象。但 v1.1 主线"家庭现金流预算"本体推迟到 v1.3。
- 决定：版本号跳过 1.1.0，直接发 1.2.0（learning-feedback 是独立 track，与现金流预算无依赖）。

## v1.0.0 — 数据能力 + 三端收口 + PWA 公网层

- 商品级小票 line items：`ExpenseItem.kind` 枚举 + `items_sum_status`、OCR 折扣 / 税 / 服务费识别、`/web` 与 Android detail kind 分组与 mismatch banner（ADR-0035）
- 家庭账本拆账邀请：跨账本邀请双 DTO 分桶、账本可见性 + 幂等 UNIQUE、`/web` 与 Android 收件箱 / 已发送 UI（ADR-0029）
- 后台任务执行模型：单进程 ThreadPoolExecutor + orphan recovery + 进度 / 取消，`/web` 任务页 + Android 任务 UI（ADR-0030）
- v0.9 → v1.0 数据迁移协议：`app_meta` + schema_version lock + 切换前强制 snapshot + 30 天 rollback CLI（ADR-0031）
- `/web` 公网层硬化：Public Web Beta 双模式（loopback + public）、`__Host-session` cookie + pairing-code 启动、Cloudflare Tunnel allowlist + WAF + Access、`/static/owner` defense-in-depth、`TicketboxBoundaryCheck` 日检（ADR-0028）
- `/web` PWA install shell：manifest + service worker + meta 标签（Issue #20）
- 后端权威 FX：唯一汇率权威 + ECB 参考 + 缺率返回 pending（ADR-0027）
- 工程化收口：服务图 cycle 清零 + audit 入 CI 门禁、`release_audit` 自动 discover `_audit_*.py`、file-backed SQLite test lane、ruff C901 复杂度门禁、`X-Request-Id` + 错误体 request_id、GET retry 指数退避 + jitter、CSV import 状态机收口
- Android settings 三屏 ViewModel refactor（Repository-injected → 标准 MVI VM）
- 公网边界 P0/P1 回归：上传 / owner / uploads 探针修正、`/u/<upload_key>` Referer/Origin 日志脱敏、非 loopback `XPJ_EXTRA_LOOPBACK_HOSTS` 拒绝、非 loopback `PUBLIC_BASE_URL` 强制 https

## v0.9.0a1 — Reports / Goals / Chart UX

- 后端 Reports、Goals、Dashboard 卡片配置 API
- Android 统计页接入 Vico 图表，Goals 和 Dashboard 卡片设置
- /web Reports 接入自托管 ECharts，保留无 JS 回退
- 三端设计 token 体系（paper/mono/midnight）
- /owner 跟随三端设计 token 视觉收口

## v0.8 — Budget / 月度可花

- 服务端月度预算、弹性预算、分类预算
- "本月可花"卡片：Android 首页 + /web Dashboard
- 共享预算（仅共享账本）和预算排除分类
- 三端 Dashboard UI/UX 基线统一

## v0.6-v0.7 — Recurring + Rules + Tags + Merchant

- 固定支出正式化（recurring_items 表 + 状态机）
- 通知草稿幂等、通知偏好开关
- 商家别名、标签多对多、规则增强
- dry-run + 审计 + 回滚
- 分类组管理和性能索引

## v0.5 — Household 权限硬化

- owner/member/viewer 角色模型全链路强约束
- 成员审计、owner 转让、viewer 写保护
- 三端角色词统一（拥有者/成员/只读）
- 邀请安全（防误绑定、一次性明文码）

## v0.4 — 多账本 + 三端架构 + Smart Ledger Engine + 家庭账本

- v0.4-alpha1: 多账本地基（ledger_id 隔离、Room v4）
- v0.4-alpha2: 三端信息架构（Android 生活流 / /web 桌面流 / /owner 管理流）
- v0.4-alpha3: Smart Ledger Engine（报表、数据质量、Rules、Recurring 候选、Review Workflow）
- v0.4-beta1: 家庭账本地基（邀请、权限、隐私不变量）

## v0.3 — 身份系统重做

- Account / Ledger / Device / AuthToken / UploadLink / PairingCode 六表
- Owner Console + /web 网页版 + iPhone UploadLink
- 公网边界 35/35 验收
- identity_schema=v0.3 确立（至今不变）
