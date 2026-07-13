# Architecture Decision Records (ADR)

按编号排序。schema-v2 ADR 的 TOML front matter 是其状态、责任人与关系的唯一权威；尚未迁移的
legacy ADR 由 [哈希 baseline](legacy-baseline.json) 冻结元数据与正文，修改时必须迁入 schema-v2。
本页索引、[当前状态账本](../current/ADR_STATUS.md)、
[机器注册表](../current/adr-registry.json) 与
[依赖图](../current/ADR_DEPENDENCY_GRAPH.md) 均由同一解析器生成，不得人工维护表格。

决定历史保留；方向变化写新 ADR 并声明 `amends` / `supersedes`。决策、实现和验证三种状态分离，
实施进度或新证据不得回写成“当时就已实现”。完整契约见 [[0065]]、
[ADR 契约标准](../rules/ADR_CONTRACT_STANDARD.md) 与 [schema-v2 模板](../rules/ADR_TEMPLATE.md)。

**编号规则**：使用四位十进制 ID；下一个可用 ID 由下方生成区给出。0018 保留 rejected tombstone，0032–0034 为保留号，不得复用。

## 索引

<!-- ADR_INDEX_TABLE_START -->
| # | 标题 | 一句话 | 状态 | 关系 |
|---|---|---|---|---|
| [0001](0001-money-uses-cents.md) | 金额使用分保存 | 历史决定：整数金额、禁 float；当前 minor-unit 语义见 0061 | accepted / nonconformant / failed | amended-by 0061 |
| [0002](0002-expense-time-vs-created-at.md) | 区分消费时间和创建时间 | 统计优先 `expense_time`，空时回退 `confirmed_at` | superseded / implemented / stale | — |
| [0003](0003-uploads-not-public.md) | uploads 不公开暴露 | 图片只能经鉴权 `GET /api/expenses/{id}/image` 取 | accepted / implemented / unverified | — |
| [0004](0004-auth-check-not-health.md) | 绑定服务器使用认证检查接口 | 绑定校验用 `/api/auth/check`，不用 `/api/health` | accepted / implemented / unverified | — |
| [0005](0005-room-serverid-upsert.md) | Room `(ledgerId, serverId)` 唯一同步 | 本地 upsert 以账本作用域避免跨账本改写 | accepted / implemented / unverified | — |
| [0006](0006-windows-powershell-utf8-bom.md) | Windows PowerShell 脚本用 UTF-8 with BOM | `.ps1` 带 BOM，`.env` 不带 BOM | accepted / implemented / unverified | — |
| [0007](0007-real-device-preflight.md) | 实机联调预检 | 双层预检：本机脚本 + App 设置页自检 | deprecated / implemented / stale | — |
| [0008](0008-public-uuid-and-theme-json.md) | 公共 UUID 与主题 JSON 边界 | `public_id` 用于跨端；主题 JSON 不暴露 UI | accepted / implemented / unverified | — |
| [0009](0009-android-version-catalog.md) | Android 依赖用 Version Catalog | 版本统一在 `libs.versions.toml` | accepted / nonconformant / failed | — |
| [0010](0010-dependency-version-audit.md) | 依赖版本审计 | `check_dependency_versions.ps1` 默认只报告 | accepted / implemented / unverified | — |
| [0011](0011-android-toolchain-upgrade.md) | Android 构建工具链升级 | AGP 9.2 / Gradle 9.4.1 / Kotlin 2.3 | deprecated / implemented / stale | — |
| [0012](0012-app-error-copy-vs-diagnostics.md) | App 错误文案与诊断日志分离 | 主流程生活化文案，技术细节进 Logcat | accepted / nonconformant / failed | — |
| [0013](0013-category-catalog-and-legacy-alias.md) | 分类目录与旧分类兼容 | 13 类默认，`吃饭` 归一到 `餐饮` | accepted / implemented / unverified | — |
| [0014](0014-ios-shortcut-file-body.md) | iOS Shortcut 使用 File body | 快捷指令首选 File 而非 Form | deprecated / implemented / stale | — |
| [0015](0015-ocr-provider-pipeline.md) | OCR Provider Pipeline | 三层 provider / parse / expense；`OCR_AUTO_RUN` 默认关 | accepted / partial / unverified | — |
| [0016](0016-performance-and-stability-baseline.md) | 性能与稳定性基线 | SQL 层聚合 + Retrofit 复用 + 批量 upsert + 限并发缩略图 | superseded / nonconformant / failed | amended-by 0041 |
| [0017](0017-gray-release-product-boundary.md) | 灰度版产品边界 | 普通用户不看 token / 域名 / 端口 / 诊断 | superseded / implemented / stale | — |
| [0018](0018-withdrawn.md) | 已撤回决定的编号墓碑 | 0018 没有可恢复的决定本体，保持 rejected tombstone 且永不复用编号 | rejected / not-started / unverified | — |
| [0019](0019-android-custom-background-local-only.md) | Android 自定义背景只做本机 | Picker 单图 + 私有目录 + DataStore，不上传 | accepted / partial / unverified | — |
| [0020](0020-alipay-receipt-rule-priority.md) | 支付宝账单 OCR 规则优先级 | 候选 + 打分 + 维度模型，禁 if 分支堆砌 | deprecated / implemented / stale | — |
| [0021](0021-ocr-draft-field-provenance.md) | OCR 草稿字段来源 | `ocr_draft_fields` 记录字段来源；用户改过不再覆盖 | accepted / partial / unverified | refines 0015 |
| [0022](0022-family-ledger-permission-model.md) | 家庭账本权限模型 | owner / member / viewer 三态 + 邀请 token；账户隔离不破 | superseded / nonconformant / failed | amended-by 0028 |
| [0023](0023-chart-library-policy.md) | 图表库引入政策 | 阶段化：v0.9 经审计后可引入展示层图表库 | accepted / implemented / unverified | — |
| [0024](0024-tri-surface-ui-ux-unification.md) | 三端 UI/UX 美化统一 | 统一设计语言，不强行同屏复刻 | accepted / nonconformant / failed | amended-by 0028 |
| [0025](0025-v0.9-android-chart-library-vico.md) | Android 图表库 Vico 3.1.0 | Vico 进 Compose 展示层；已被 0055 回收 | superseded / implemented / stale | depends-on 0023 |
| [0026](0026-v0.9-web-chart-library-echarts.md) | /web 图表库 ECharts 6.0.0 | 自托管 ECharts，禁 CDN | accepted / partial / unverified | depends-on 0023 |
| [0027](0027-backend-authoritative-fx.md) | Backend Authoritative FX | 后端唯一汇率权威；冻结快照；缺率返 pending | accepted / nonconformant / failed | amended-by 0061 |
| [0028](0028-public-web-session-gated.md) | Public Web Session-Gated Surface | `/web` 公网仅以后端 web session + Cloudflare allowlist 方式开放，`/owner` 仍 loopback | accepted / nonconformant / failed | amends 0022; amends 0024 |
| [0029](0029-household-bill-split-privacy.md) | Household Bill Split Privacy | 跨账本邀请双 DTO 分桶；账本可见性 + 幂等 UNIQUE | accepted / nonconformant / failed | — |
| [0030](0030-long-task-execution-model.md) | Long Task Execution Model | 单进程 ThreadPoolExecutor + PG progress table + orphan recovery | superseded / implemented / stale | refines 0016 |
| [0031](0031-v1-data-migration-protocol.md) | v1.0 Data Migration Protocol | 一次性 SQLite cut-over 历史；仅 compatibility gate 继续有效 | superseded / implemented / stale | depends-on 0030 |
| [0035](0035-line-items-discount-tax-mismatch.md) | Line Items Discount/Tax Mismatch | line item kind enum + items_sum_status；items 不再要求总额等于 expense | accepted / implemented / unverified | — |
| [0036](0036-v1.1-ai-budget-provider-privacy-boundary.md) | v1.1 AI Budget Provider Privacy | AI 只看最小结构化摘要 + 本地映射表；不上传原始账本 / 图片 / 真名 / 路径 | accepted / partial / unverified | — |
| [0037](0037-v1.2-learning-feedback-dual-tables.md) | v1.2 Learning Feedback Dual Tables | algorithm_decisions / ledger_learning_events / ocr_facts 三表 append-only 建议层，不污染账本 | accepted / partial / unverified | refines 0021 |
| [0038](0038-v1.3-multi-surface-sync.md) | v1.3 Multi-Surface Sync | row_version OCC + Android outbox + 显式冲突；当前扩展见后续 ADR | accepted / nonconformant / failed | amended-by 0041; amended-by 0042 |
| [0039](0039-adr-implementation-calibration.md) | ADR Implementation Calibration | `54c21841` 历史校准快照，不再承载当前状态 | superseded / implemented / stale | — |
| [0040](0040-outbox-subresource-target-and-child-undo.md) | outbox 子资源 target_id + 子资源 undo 契约 | 子资源锚父 Expense `row_version`（无自有 token）；undo 只翻父行不重放子资源 | accepted / partial / unverified | refines 0038 |
| [0041](0041-postgresql-engine-migration.md) | 存储层完整性债清偿 | 当前运行时 PostgreSQL-only + row_version CAS；SQLite fallback 是 cut-over 前历史方案，已退役 | accepted / nonconformant / failed | amends 0016; amends 0038 |
| [0042](0042-offline-availability-and-request-idempotency.md) | 离线可用性边界 + 请求幂等键 | outbox-routed mutate 使用 intent-time key，分离 OCC 与安全 replay | accepted / nonconformant / failed | amends 0038; amended-by 0057 |
| [0043](0043-tag-management.md) | 标签管理 rename / delete / merge | online-only mutate surface；Tag 进 row_version CAS；delete / merge 带 undo 表 | accepted / implemented / unverified | — |
| [0044](0044-android-string-resourcing.md) | Android UI 字符串外置 strings.xml | resourcing 非翻译：只放中文、不建第二语言；按 screen/module 分 PR | accepted / implemented / unverified | — |
| [0045](0045-csrf-signing-key.md) | CSRF 持久化随机签名密钥 | 公开占位常量 → app_meta 随机秘密，启动 fail closed | accepted / nonconformant / failed | amended-by 0059 |
| [0046](0046-android-recurring-reminder-detection-source.md) | Android 固定支出提醒检测源 | WorkManager 只作 Scheduler；Engine/Policy/Store/Dispatcher 分层 | accepted / nonconformant / failed | amended-by 0058 |
| [0047](0047-bundled-installer-windows-services.md) | 捆绑安装器 + Windows 服务化 + 主机管理器 | Windows 服务化与家庭分发方向；实施状态单独跟踪 | accepted / nonconformant / failed | depends-on 0041; depends-on 0028; depends-on 0045; amended-by 0062; amended-by 0063; amended-by 0064 |
| [0048](0048-rive-mascot-animation.md) | Rive 吉祥物动画方案（已放弃） | Rive 导出付费墙导致方案撤回；当前使用原生 Compose | rejected / not-started / stale | — |
| [0049](0049-debt-domain-contract.md) | Debt Domain Contract | frozen obligation + append-only repayment/correction/forgiveness facts | accepted / nonconformant / failed | depends-on 0001; depends-on 0068; depends-on 0027; depends-on 0029; depends-on 0038; depends-on 0041; depends-on 0042; amended-by 0060 |
| [0050](0050-android-baseline-profile-prerelease.md) | Android Baseline Profile 预发布工具 | issue #64 A1：AGP 9.2 上稳定版 baselineprofile 报废（实证），owner 拍板采 1.5.0-alpha06；仅构建/测试期、不进运行时，回收=1.5.0 stable | accepted / implemented / unverified | depends-on 0009; depends-on 0010; informational 0011 |
| [0051](0051-unified-recycle-bin.md) | 统一回收站 | owner / web / Android 回收站；5 分钟 undo 与 30 天 recycle 分离 | accepted / partial / unverified | refines 0038 |
| [0052](0052-master-delete-recycle-bin-scope.md) | 主数据删除与回收站边界 | 历史事实不随 master 删除改写；按领域归档/隐藏 | accepted / partial / unverified | refines 0051 |
| [0053](0053-merchant-catalog-contract.md) | 商家目录与删除边界 | ledger catalog 删除不批量改写历史 `Expense.merchant` | accepted / implemented / unverified | refines 0052 |
| [0054](0054-merchant-catalog-merge-rename.md) | 商家目录合并与重命名契约 | rename 不修历史；merge 双 token + 显式 alias policy | accepted / partial / unverified | refines 0053 |
| [0055](0055-android-chart-native-canvas-tokens.md) | Android 图表回收到原生 Canvas 与设计 token | 删除 Vico 运行时依赖；洞察页趋势图只用单一图表语义和 tokenized Canvas | accepted / implemented / unverified | supersedes 0025 |
| [0056](0056-adr-lifecycle-current-state-ledger.md) | ADR 历史与实施状态分离 | 保留不可改写的决定历史，并把当前实施状态与 lineage 单独维护 | superseded / implemented / stale | supersedes 0039; informational 0065 |
| [0057](0057-idempotency-stable-result-and-single-transaction-claim.md) | 请求幂等的稳定首次结果与单事务 claim | 同一意图只提交一次，并在当前授权成立时重放最小稳定首次结果 | accepted / nonconformant / failed | amends 0042 |
| [0058](0058-recurring-reminder-delivery-semantics.md) | 固定支出提醒的 best-effort 投递语义 | 提醒尽量不漏并压低重复，但不宣称准点或 exactly-once | accepted / nonconformant / failed | amends 0046 |
| [0059](0059-persisted-secret-restore-and-clone-identity.md) | 持久 secret 的 restore、clone 与恢复主体 | same-install 保留 signing identity但撤销回滚 bearer，clone 重建安全域，并保留独立 owner re-enrollment 根 | accepted / nonconformant / failed | amends 0045 |
| [0060](0060-debt-forgiveness-fold-calibration.md) | Debt forgiveness fold 与事实重建 | forgiveness 减少 remaining但不增加 paid，DebtVoid 必须进入纯事实灾难重建 | accepted / nonconformant / failed | amends 0049 |
| [0061](0061-home-currency-minor-unit-semantics.md) | Home currency 与整数 minor-unit 绑定 | 兼容 *_cents 字段名，但金额语义由持久 installation currency revision 与显式 exponent 裁决 | accepted / nonconformant / failed | amends 0001; amends 0027 |
| [0062](0062-windows-installer-lifecycle-transaction.md) | Windows 安装事务：生命周期回执、复制边界与恢复协议 | 用机器锁、持久回执和复制边界区分可补偿失败与必须 repair 的故障隔离 | accepted / nonconformant / failed | amends 0047; depends-on 0041; informational 0006; amended-by 0074 |
| [0063](0063-recoverable-owner-bootstrap-ceremony.md) | 可恢复 Owner Bootstrap：确定性凭据、全局串行化与关闭窗口 | 以家庭 owner 身份 claim 为核心，隔离可恢复创建、可撤销子凭证和安装交接 | accepted / partial / failed | amends 0047; depends-on 0028; depends-on 0045; amended-by 0074 |
| [0064](0064-windows-installer-build-provenance.md) | Windows 安装器构建 Provenance：本地快照证据与上游信任边界 | 区分本地 payload 完整性、actual-input binding、上游真实性与最终发布 attestation | accepted / partial / unverified | amends 0047; depends-on 0010; depends-on 0062 |
| [0065](0065-executable-architecture-contract-governance.md) | ADR 可执行架构契约与渐进式治理 | 用 front matter、稳定 clause、base-relative ratchet、派生证据和生成 registry 把 ADR 变成可验证契约 | accepted / partial / unverified | supersedes 0056 |
| [0066](0066-family-financial-fact-system-boundary.md) | 小票夹作为家庭账务事实系统的领域与适配边界 | 以家庭账务事实、身份和多端协作为核心，替代早期小票上传器产品边界 | accepted / partial / unverified | supersedes 0017; refines 0024; refines 0041 |
| [0067](0067-postgresql-schema-lifecycle-and-rollback.md) | PostgreSQL schema 生命周期：先兼容、后备份、单迁移者升级与可证明恢复 | 结构化账本只有在只读检查、兼容性裁决、已验证恢复点、单迁移者 Alembic 和幂等 seed 全部成功后才可开放写入 | accepted / nonconformant / failed | supersedes 0031; refines 0041; refines 0066; depends-on 0062 |
| [0068](0068-family-identity-rbac-and-trust-boundaries.md) | 家庭身份、账本 RBAC 与运行/恢复信任边界 | 分离家庭成员、账本 owner、设备会话、上传入口、维护和恢复权限 | accepted / nonconformant / failed | supersedes 0022; refines 0028; refines 0045; refines 0059; refines 0063 |
| [0069](0069-offline-intent-binding-and-protocol-evolution.md) | 离线意图、绑定退出与跨版本重放协议 | 把可重建 Room 投影与不可静默丢弃的用户意图分离，以版本化 envelope、绑定退出 ceremony、OCC 和稳定幂等结果保护长期离线多端写入 | accepted / nonconformant / failed | refines 0038; refines 0042; refines 0057; refines 0061; refines 0066 |
| [0070](0070-accounting-time-and-calendar-binding.md) | 账务时间、归属日期与账本 calendar binding | 分离事件瞬时、账务归属日期和系统审计时间，禁止请求时区重切历史月份 | accepted / nonconformant / failed | supersedes 0002; refines 0061; refines 0066; depends-on 0067 |
| [0071](0071-receipt-asset-authority-and-recovery.md) | 收据附件的复合权威、崩溃一致性与同代恢复 | 规范化收据 bytes 与 PostgreSQL 中的账本归属、生命周期和预期摘要共同构成有效附件，缩略图仅是可重建缓存 | accepted / nonconformant / failed | refines 0003; refines 0059; refines 0066; depends-on 0067 |
| [0072](0072-postgresql-capacity-backpressure-and-task-execution.md) | PostgreSQL 容量、背压与可恢复后台任务执行 | 用 PG 任务账本和可替换 executor 隔离长任务，替代 SQLite/进程内永久假设 | accepted / nonconformant / failed | supersedes 0016; supersedes 0030; refines 0066; depends-on 0067 |
| [0073](0073-financial-facts-corrections-and-projections.md) | 家庭财务事实、更正、冲正与投影契约 | 区分建议、意图、计划、当前事实聚合、追加事实与投影，并为金额、更正、退款、债务重建和删除建立统一边界 | accepted / nonconformant / failed | refines 0001; refines 0027; refines 0029; refines 0035; refines 0015; refines 0036; refines 0037; refines 0049; refines 0051; refines 0052; refines 0060; refines 0061; refines 0066; refines 0070 |
| [0074](0074-windows-installer-state-authority-and-owner-handoff.md) | Windows 安装器状态权限域与 owner handoff 原子交接 | 分置 installer 权威与 backend-readable 运行投影，以不可变进程身份、原子状态机和显式租约交接完成可重入安装事务 | accepted / partial / unverified | amends 0062; amends 0063; depends-on 0065; refines 0066; informational 0006 |
<!-- ADR_INDEX_TABLE_END -->

## 编写新 ADR

<!-- ADR_NEXT_ID_START -->
下一编号 `0075`。
<!-- ADR_NEXT_ID_END -->

命名 `NNNN-kebab-case-topic.md`，从
[schema-v2 模板](../rules/ADR_TEMPLATE.md) 创建。新 ADR 必须通过：

```powershell
python backend/scripts/render_adr_contract_views.py
python backend/scripts/_audit_adr_contracts.py
```

生成器是唯一允许改写本页表格的入口。局部语义变化用 `amends`，整体替代用 `supersedes`；
长实施方案、runbook 和证据记录应由稳定 clause ID 链接，不复制进决定本体。
