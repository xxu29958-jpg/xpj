# Architecture Decision Records (ADR)

按编号排序。每份 ADR 一旦下发不再修改；如方向变了写新的 ADR 并标 supersedes。

**编号范围**：0001–0053（0018 已撤回；0032–0034 未使用，编号跳过）。

## 索引

| # | 标题 | 一句话 | 关联 |
|---|---|---|---|
| [0001](0001-money-uses-cents.md) | 金额使用分保存 | 全链路 `amount_cents` 整数；禁止 float/元 | — |
| [0002](0002-expense-time-vs-created-at.md) | 区分消费时间和创建时间 | 统计优先 `expense_time`，空时回退 `confirmed_at` | — |
| [0003](0003-uploads-not-public.md) | uploads 不公开暴露 | 图片只能经鉴权 `GET /api/expenses/{id}/image` 取 | — |
| [0004](0004-auth-check-not-health.md) | 绑定服务器使用认证检查接口 | 绑定校验用 `/api/auth/check`，不用 `/api/health` | — |
| [0005](0005-room-serverid-upsert.md) | Room `(ledgerId, serverId)` 唯一同步 | 本地 upsert 以账本作用域避免跨账本改写 | — |
| [0006](0006-windows-powershell-utf8-bom.md) | Windows PowerShell 脚本用 UTF-8 with BOM | `.ps1` 带 BOM，`.env` 不带 BOM | — |
| [0007](0007-real-device-preflight.md) | 实机联调预检 | 双层预检：本机脚本 + App 设置页自检 | — |
| [0008](0008-public-uuid-and-theme-json.md) | 公共 UUID 与主题 JSON 边界 | `public_id` 用于跨端；主题 JSON 不暴露 UI | — |
| [0009](0009-android-version-catalog.md) | Android 依赖用 Version Catalog | 版本统一在 `libs.versions.toml` | — |
| [0010](0010-dependency-version-audit.md) | 依赖版本审计 | `check_dependency_versions.ps1` 默认只报告 | 与 [rules/DEPENDENCIES.md](../rules/DEPENDENCIES.md) 互补 |
| [0011](0011-android-toolchain-upgrade.md) | Android 构建工具链升级 | AGP 9.2 / Gradle 9.4.1 / Kotlin 2.3 | 信息性档案 |
| [0012](0012-app-error-copy-vs-diagnostics.md) | App 错误文案与诊断日志分离 | 主流程生活化文案，技术细节进 Logcat | — |
| [0013](0013-category-catalog-and-legacy-alias.md) | 分类目录与旧分类兼容 | 13 类默认，`吃饭` 归一到 `餐饮` | — |
| [0014](0014-ios-shortcut-file-body.md) | iOS Shortcut 使用 File body | 快捷指令首选 File 而非 Form | — |
| [0015](0015-ocr-provider-pipeline.md) | OCR Provider Pipeline | 三层 provider / parse / expense；`OCR_AUTO_RUN` 默认关 | — |
| [0016](0016-performance-and-stability-baseline.md) | 性能与稳定性基线 | SQL 层聚合 + Retrofit 复用 + 批量 upsert + 限并发缩略图 | — |
| [0017](0017-gray-release-product-boundary.md) | 灰度版产品边界 | 普通用户不看 token / 域名 / 端口 / 诊断 | — |
| 0018 | — | **已撤回** | — |
| [0019](0019-android-custom-background-local-only.md) | Android 自定义背景只做本机 | Picker 单图 + 私有目录 + DataStore，不上传 | 边界文档 [ANDROID_APPEARANCE_BACKGROUND.md](../architecture/ANDROID_APPEARANCE_BACKGROUND.md) 引用 |
| [0020](0020-alipay-receipt-rule-priority.md) | 支付宝账单 OCR 规则优先级 | 候选 + 打分 + 维度模型，禁 if 分支堆砌 | — |
| [0021](0021-ocr-draft-field-provenance.md) | OCR 草稿字段来源 | `ocr_draft_fields` 记录字段来源；用户改过不再覆盖 | — |
| [0022](0022-family-ledger-permission-model.md) | 家庭账本权限模型 | owner / member / viewer 三态 + 邀请 token；账户隔离不破 | v0.5 收口见 [CHANGELOG](../current/CHANGELOG.md) |
| [0023](0023-chart-library-policy.md) | 图表库引入政策 | 阶段化：v0.9 经审计后可引入展示层图表库 | 政策层 → 0025 / 0026 是其落地 |
| [0024](0024-tri-surface-ui-ux-unification.md) | 三端 UI/UX 美化统一 | 统一设计语言，不强行同屏复刻 | — |
| [0025](0025-v0.9-android-chart-library-vico.md) | Android 图表库 Vico 3.1.0 | Vico 进 Compose 展示层 | 0023 下落地 |
| [0026](0026-v0.9-web-chart-library-echarts.md) | /web 图表库 ECharts 6.0.0 | 自托管 ECharts，禁 CDN | 0023 下落地 |
| [0027](0027-backend-authoritative-fx.md) | Backend Authoritative FX | 后端唯一汇率权威；ECB 参考；缺率返 pending | — |
| [0028](0028-public-web-session-gated.md) | Public Web Session-Gated Surface | `/web` 公网仅以后端 web session + Cloudflare allowlist 方式开放，`/owner` 仍 loopback | 公网边界 |
| [0029](0029-household-bill-split-privacy.md) | Household Bill Split Privacy | 跨账本邀请双 DTO 分桶；账本可见性 + 幂等 UNIQUE | v1.0 拆账隐私边界 |
| [0030](0030-long-task-execution-model.md) | Long Task Execution Model | 单进程 ThreadPoolExecutor + orphan recovery；SQLite 进度表 | csv_import / v1_migration / 通用长任务 |
| [0031](0031-v1-data-migration-protocol.md) | v1.0 Data Migration Protocol | app_meta schema_version lock + pre-v1.0 backup snapshot + 30 天 rollback CLI | v1.0 cut-over 协议 |
| [0035](0035-line-items-discount-tax-mismatch.md) | Line Items Discount/Tax Mismatch | line item kind enum + items_sum_status；items 不再要求总额等于 expense | 商品级小票 |
| [0036](0036-v1.1-ai-budget-provider-privacy-boundary.md) | v1.1 AI Budget Provider Privacy | AI 只看最小结构化摘要 + 本地映射表；不上传原始账本 / 图片 / 真名 / 路径 | v1.1 AI 预算隐私边界 |
| [0037](0037-v1.2-learning-feedback-dual-tables.md) | v1.2 Learning Feedback Dual Tables | algorithm_decisions / ledger_learning_events / ocr_facts 三表 append-only 建议层，不污染账本 | v1.2 学习反馈底层 |
| [0038](0038-v1.3-multi-surface-sync.md) | v1.3 Multi-Surface Sync | mutate endpoint body `expected_updated_at` + 409 `state_conflict`；Android Room offline outbox + WorkManager drain；soft-delete + 5s undo window | v1.3 同步 invariant |
| [0039](0039-adr-implementation-calibration.md) | ADR Implementation Calibration | 校准 0001–0038 的当前实现状态；区分仍绑定、文字漂移、真实待修和计划未完成 | ADR 审计校准 |
| [0040](0040-outbox-subresource-target-and-child-undo.md) | outbox 子资源 target_id + 子资源 undo 契约 | 子资源锚父 Expense `row_version`（无自有 token）；undo 只翻父行不重放子资源 | accepted；[[0038]]/[[0041]]/[[0042]] |
| [0041](0041-postgresql-engine-migration.md) | 存储层完整性债清偿 | 开发期一次性清存储层债：本机自托管 Postgres + row_version 替 `updated_at`-as-CAS；SQLite+row_version 保留为 fallback | accepted；[[0038]] 升级 |
| [0042](0042-offline-availability-and-request-idempotency.md) | 离线可用性边界 + 请求幂等键 | 堵 committed-but-unseen 假 409：outbox-routed mutate 面加请求幂等键（独立表 + intent-time UUID + key 先于 OCC）；离线边界判据升为契约；批改走客户端 fan-out | accepted；[[0038]]/[[0041]]；解除 §14 deferral |
| [0043](0043-tag-management.md) | 标签管理 rename / delete / merge | online-only mutate surface；Tag 进 row_version CAS；delete / merge 带 undo 表 | accepted；[[0038]] 同步模型外的在线面 |
| [0044](0044-android-string-resourcing.md) | Android UI 字符串外置 strings.xml | resourcing 非翻译：只放中文、不建第二语言；按 screen/module 分 PR | accepted；反转 §14 deferral，§13 i18n 仍不做 |
| [0045](0045-csrf-signing-key.md) | CSRF 签名密钥 per-install 化 | 公开占位常量 → app_meta 持久化随机密钥派生（budget-advisor audit HMAC 同源） | accepted |
| [0046](0046-android-recurring-reminder-detection-source.md) | Android 固定支出提醒检测源 | WorkManager 仅作 Scheduler；Engine/Policy/Store/Dispatcher 四层契约；本地 sent-key 去重；不触 §13 MAJOR | accepted；recurring 通知出口见 notif-loop PR-2 |
| [0047](0047-bundled-installer-windows-services.md) | 分发形态：捆绑安装器 + PG/后端注册 Windows 服务 + 主机管理器 | PG+后端各注册 Windows 服务（SCM 当守护，否决便携双进程守护；后端用 **Shawl** 包，**NSSM 弃维否决**；Shawl ctrl-C+`--stop-timeout` 调大 graceful）；**各用独立虚拟服务账户 `NT SERVICE\…`**；**数据默认 `C:\ProgramData\Ticketbox`（高级可改位置，断 ACL 继承、升级不偷换、卸载默认留数据、迁移走管理器）**；PG 隐形+应用角色建库堵 owner 陷阱+connect-retry 必需；**覆盖升级前置 `pre_upgrade` 快照失败即中止**；EXE=控制台管理器（bootstrap/配设备走 loopback API、二维码只塞短期 pairing code 不塞 token、/owner 永远 loopback）；网络用户自配（LAN 优先 mDNS+NsdManager 自愈漂移，远程**荐 Tailscale**、named tunnel 进阶，永不在 plain-http 设 `__Host-` cookie）；PG major 钉死 17；**默认不签**（SAC 可逆上 Trusted Signing） | **accepted**（owner 2026-06-18 拍板+联网验证+补强服务身份/数据目录/ACL/升级前置，运行时未实现） |
| [0048](0048-rive-mascot-animation.md) | 吉祥物「夹夹」动画技术栈 = Rive | MIT runtime；`.riv` 本地加载零联网；只用稳定 View API（beta Compose API 不进主线）；一套 artboard 喂三端 + 运行时绑 token 色；纯表现层不写业务 | **proposed**（角色 brief = docs/roadmap/MASCOT_BRIEF.md，原画 v3 已定稿） |
| [0049](0049-debt-domain-contract.md) | Debt Domain Contract | 统一 Debt obligation：家庭内欠款与外部负债同表，Repayment/Adjustment append-only，bill_split accept 可原子生成 Debt，debt_repayment goal 读取 Debt 清偿状态 | accepted target contract；[[0029]]/[[0038]]/[[0041]]/[[0042]]/[[0048]] |
| [0050](0050-android-baseline-profile-prerelease.md) | Android Baseline Profile 预发布工具 | issue #64 A1：AGP 9.2 上稳定版 baselineprofile 报废（实证），owner 拍板采 1.5.0-alpha06；仅构建/测试期、不进运行时，回收=1.5.0 stable | accepted；[[0011]]/[[0009]]/[[0010]]；detekt alpha 同形例外 |
| [0051](0051-unified-recycle-bin.md) | 统一回收站 | owner / web / Android 回收站；普通撤销 5 分钟与显式回收站 30 天 retention 解耦 | accepted / partially implemented；[[0038]]/[[0043]]/[[0049]] |
| [0052](0052-master-delete-recycle-bin-scope.md) | 主数据删除与回收站边界 | category 先做偏好目录，budget 按月度配置归档，merchant master 等 catalog ADR 后再删 | accepted target contract；[[0013]]/[[0051]] |
| [0053](0053-merchant-catalog-contract.md) | 商家目录与删除边界 | merchant catalog 是账本级目录行；删除只隐藏/软删目录，不批量改写历史 `Expense.merchant`；merge 另片 | accepted target contract；[[0051]]/[[0052]] |

## 编写新 ADR

下一编号 `0054`。命名 `NNNN-kebab-case-topic.md`。常见结构：

```markdown
# ADR-NNNN: 标题

## 背景
为什么要做这个决策；当前的痛点 / 候选方案。

## 决策
做什么；具体选型 / 边界 / 接口约定。

## 后果
影响哪些代码 / 文档 / 验收；后续需要做什么。
```

如新 ADR 覆盖旧 ADR，在新 ADR 顶部写 `Supersedes: ADR-NNNN`，并在旧 ADR 顶部加 `Superseded by: ADR-NNNN`。
