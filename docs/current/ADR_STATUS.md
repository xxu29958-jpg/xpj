# ADR 当前状态账本

本文件回答“现在什么仍绑定、实现到哪里、读哪份新决定”，不改写历史 ADR。

<!-- ADR_STATUS_METADATA_START -->
- 组合审查日期: 2026-07-12
- Review base: `83af67d0702a7bfda2fa3a760b56dbef47c663c7` (pre-implementation main snapshot)
- Baseline scope: legacy ADRs retain per-entry reviewed-against evidence; schema-v2 ADRs and the Windows installer runtime including ADR-0074 are calibrated against review base 83af67d0 plus the implementation in this tree, while unrun evidence remains unverified
<!-- ADR_STATUS_METADATA_END -->
- Governance: [[0065]]
- 状态与关系元数据权威：schema-v2 ADR 以 TOML front matter 为准；legacy ADR 的历史身份由
  [`legacy-baseline.json`](../DECISIONS/legacy-baseline.json) 冻结，当前校准由
  [`legacy-calibration.json`](../DECISIONS/legacy-calibration.json) 承担。生成的 registry、索引和本页不是新的架构权威。

状态定义：

- `decision_status`: `proposed | accepted | rejected | deprecated | superseded`
- `implementation_status`: `not-started | implementing | partial | implemented | nonconformant`
- `verification_status`: `unverified | verified | failed | stale`

`implemented` 只表示实现声称完成；只有达到条款所需证明强度且证据仍新鲜，才能标 `verified`。
实现偏离已接受决定时标 `nonconformant`，不得通过修改历史决定掩盖。索引、状态表、JSON registry
和依赖图全部从同一权威生成；本页表格不得人工编辑。

## Registry

<!-- ADR_STATUS_TABLE_START -->
| ADR | 决策状态 | 实现状态 | 验证状态 | 当前有效范围 | 关系 |
| --- | --- | --- | --- | --- | --- |
| [0001](../DECISIONS/0001-money-uses-cents.md) | accepted | nonconformant | failed | ADR-0001 未被后继关系覆盖的 declared_current_scope：权威金额使用有界整数 minor-unit 与显式币种；0061/0073 定义 binding、舍入、更正和投影；当前修订：ADR-0061 后继修订（金额单位从固定人民币分收紧为 currency-aware integer minor units）：ADR-0061 未被后继关系覆盖的 declared_current_scope：home-currency identity、minor-unit exponent、rounding、跨端 capability 与 FX snapshot；当前修订：ADR-0075 后继修订（C02/C03 全量持久绑定未落地期间的最小写时桥接门；不替代版本化绑定行与修订握手）：currency_binding_drift 写时门（debt/proposal/expense 盖章入口）、读路径降级分工、与全量持久绑定的边界 | amended-by 0061 |
| [0002](../DECISIONS/0002-expense-time-vs-created-at.md) | superseded | implemented | stale | 仅保留事件时间与记录创建时间分离的历史原则；现行账务 calendar binding 由 0070 裁决 | — |
| [0003](../DECISIONS/0003-uploads-not-public.md) | accepted | implemented | unverified | 收据原图不得静态公开；资产权威、完整性、同代备份与恢复由 0071 refine | — |
| [0004](../DECISIONS/0004-auth-check-not-health.md) | accepted | implemented | unverified | 连接预检分别证明可达性与已鉴权 identity/capability；不永久冻结检查 URL | — |
| [0005](../DECISIONS/0005-room-serverid-upsert.md) | accepted | implemented | unverified | Room confirmed 数据仅是按 server/ledger/resource identity 可重建投影；离线 intent 由 0069 裁决 | — |
| [0006](../DECISIONS/0006-windows-powershell-utf8-bom.md) | accepted | implemented | unverified | 仅 Windows adapter 的 PowerShell 5.1 BOM/CRLF 兼容，不进入领域核心 | — |
| [0007](../DECISIONS/0007-real-device-preflight.md) | deprecated | implemented | stale | 历史 iPhone→Windows→Android 实机 profile；已迁出架构决定并转版本化 runbook | — |
| [0008](../DECISIONS/0008-public-uuid-and-theme-json.md) | accepted | implemented | unverified | 公共资源 ID 协议与 Android local-only 主题配置是两项独立边界，待拆分治理 | — |
| [0009](../DECISIONS/0009-android-version-catalog.md) | accepted | nonconformant | failed | Android 依赖版本与 constraints 统一进入 catalog；预发布仅允许有期限、有退出条件的例外 | — |
| [0010](../DECISIONS/0010-dependency-version-audit.md) | accepted | implemented | unverified | 依赖 freshness advisory 与许可证、漏洞、来源、hash、provenance release gate 分离 | — |
| [0011](../DECISIONS/0011-android-toolchain-upgrade.md) | deprecated | implemented | stale | 历史 AGP/Gradle/Kotlin/KSP 升级快照；现由依赖注册表和显式例外裁决 | — |
| [0012](../DECISIONS/0012-app-error-copy-vs-diagnostics.md) | accepted | nonconformant | failed | 稳定用户错误语义与脱敏诊断分离；写失败说明副作用、outbox、冲突与重试安全 | — |
| [0013](../DECISIONS/0013-category-catalog-and-legacy-alias.md) | accepted | implemented | unverified | 分类是可演进 catalog；跨端 alias、版本兼容、迁移与退役必须显式 | — |
| [0014](../DECISIONS/0014-ios-shortcut-file-body.md) | deprecated | implemented | stale | 历史 iOS Shortcut 互操作 runbook；上传能力、UploadLink、限额和流式校验由现行协议裁决 | — |
| [0015](../DECISIONS/0015-ocr-provider-pipeline.md) | accepted | partial | unverified | OCR provider/parse/fact/draft 分层；建议可追踪、人工确认入账、provider 最小外发且有背压 | — |
| [0016](../DECISIONS/0016-performance-and-stability-baseline.md) | superseded | nonconformant | failed | ADR-0016 未被后继关系覆盖的 declared_current_scope：历史 SQLite/无后台框架性能基线；当前 PostgreSQL 容量、背压、任务事实与 executor adapter 由 0072 裁决；当前修订：ADR-0041 后继修订（SQLite 部署条款）：PostgreSQL-only 与 row_version 仍有效；schema lifecycle 由 0067、容量与任务由 0072 裁决 | amended-by 0041 |
| [0017](../DECISIONS/0017-gray-release-product-boundary.md) | superseded | implemented | stale | 历史灰度上传工具产品边界；当前家庭账务事实系统及八承重域由 0066 裁决 | — |
| [0018](../DECISIONS/0018-withdrawn.md) | rejected | not-started | unverified | 仅保存缺失历史与编号不可复用事实，不产生任何产品或实现契约 | — |
| [0019](../DECISIONS/0019-android-custom-background-local-only.md) | accepted | partial | unverified | Android 自定义背景只保存在本机私有空间且不得上传；格式、大小和异常 provider 必须有界 | — |
| [0020](../DECISIONS/0020-alipay-receipt-rule-priority.md) | deprecated | implemented | stale | 历史支付宝固定词表/权重；当前仅保留可解释候选、置信度、人工确认，算法进入版本化 registry/golden corpus | — |
| [0021](../DECISIONS/0021-ocr-draft-field-provenance.md) | accepted | partial | unverified | OCR/AI 建议按字段记录 ownership、fact/parser version；用户修改不得被后台覆盖，legacy heuristic 必须可退役 | refines 0015 |
| [0022](../DECISIONS/0022-family-ledger-permission-model.md) | superseded | nonconformant | failed | ADR-0022 未被后继关系覆盖的 declared_current_scope：历史家庭权限矩阵；当前 Account/Ledger/Device/Token/UploadLink/Web/恢复权限由 0068 裁决；当前修订：ADR-0028 后继修订（公网 /web 权限入口）：`/web` 可公网但 session-gated；`/owner` 永远 loopback；公网 admin 默认禁止并由 0068 收紧 | amended-by 0028 |
| [0023](../DECISIONS/0023-chart-library-policy.md) | accepted | implemented | unverified | 图表仅消费结构化只读投影；依赖须可审计、可回退、无 CDN，失败不得改变账本 | — |
| [0024](../DECISIONS/0024-tri-surface-ui-ux-unification.md) | accepted | nonconformant | failed | ADR-0024 未被后继关系覆盖的 declared_current_scope：member/owner/maintainer/auditor 跨端同语言不同布局；覆盖加载、失败、副作用、a11y 与极值输入；当前修订：ADR-0028 后继修订（/web loopback 网络边界）：`/web` 可公网但 session-gated；`/owner` 永远 loopback；公网 admin 默认禁止并由 0068 收紧 | amended-by 0028 |
| [0025](../DECISIONS/0025-v0.9-android-chart-library-vico.md) | superseded | implemented | stale | Vico 选型仅保留历史；Android 图表现由 0055 的原生 Canvas/token 决定取代 | depends-on 0023 |
| [0026](../DECISIONS/0026-v0.9-web-chart-library-echarts.md) | accepted | partial | unverified | 公开 browser-session 下自托管 ECharts、CSP/digest、SSR fallback、导出与升级 gate | depends-on 0023 |
| [0027](../DECISIONS/0027-backend-authoritative-fx.md) | accepted | nonconformant | failed | ADR-0027 未被后继关系覆盖的 declared_current_scope：后端以 Decimal 和发生日裁决并冻结原币/home snapshot；0061/0073 补 currency binding 与更正事实；当前修订：ADR-0061 后继修订（home currency 从固定 CNY 收紧为持久 installation-global binding）：ADR-0061 未被后继关系覆盖的 declared_current_scope：home-currency identity、minor-unit exponent、rounding、跨端 capability 与 FX snapshot；当前修订：ADR-0075 后继修订（C02/C03 全量持久绑定未落地期间的最小写时桥接门；不替代版本化绑定行与修订握手）：currency_binding_drift 写时门（debt/proposal/expense 盖章入口）、读路径降级分工、与全量持久绑定的边界 | amended-by 0061 |
| [0028](../DECISIONS/0028-public-web-session-gated.md) | accepted | nonconformant | failed | `/web` 可公网但 session-gated；`/owner` 永远 loopback；公网 admin 默认禁止并由 0068 收紧 | amends 0022; amends 0024 |
| [0029](../DECISIONS/0029-household-bill-split-privacy.md) | accepted | nonconformant | failed | 邀请接受在单事务形成 member Expense/Debt/Claim/Audit fact bundle；可见性、撤销、双计数和重试显式 | — |
| [0030](../DECISIONS/0030-long-task-execution-model.md) | superseded | implemented | stale | 历史 SQLite/in-process 长任务模型；当前 PG task fact、幂等、恢复、背压与 executor adapter 由 0072 裁决 | refines 0016 |
| [0031](../DECISIONS/0031-v1-data-migration-protocol.md) | superseded | implemented | stale | 仅保留 v1 SQLite cut-over 历史；现行 PostgreSQL/Alembic lifecycle、mixed-version 与 rollback 由 0067 裁决 | depends-on 0030 |
| [0035](../DECISIONS/0035-line-items-discount-tax-mismatch.md) | accepted | implemented | unverified | ExpenseItem/折扣/税使用数据库约束和服务重算；sum status 是可重建投影并由 0073 收紧 | — |
| [0036](../DECISIONS/0036-v1.1-ai-budget-provider-privacy-boundary.md) | accepted | partial | unverified | AI budget provider 逐个声明最小出站 allowlist；建议不写权威预算且采纳必须人工确认 | — |
| [0037](../DECISIONS/0037-v1.2-learning-feedback-dual-tables.md) | accepted | partial | unverified | SuggestionEvent/LearningSignal/OcrFact 的 provenance、追加语义、retention、PII 与不可变证据等级 | refines 0021 |
| [0038](../DECISIONS/0038-v1.3-multi-surface-sync.md) | accepted | nonconformant | failed | ADR-0038 未被后继关系覆盖的 declared_current_scope：PostgreSQL 是账本真源，Room confirmed 是投影，outbox 是设备未提交 intent；退出、quarantine 与 mixed-version 由 0069 裁决；当前修订：ADR-0041 后继修订（CAS token 改为 row_version）：PostgreSQL-only 与 row_version 仍有效；schema lifecycle 由 0067、容量与任务由 0072 裁决；ADR-0042 后继修订（outbox-routed request idempotency）：ADR-0042 未被后继关系覆盖的 declared_current_scope：outbox intent key、fingerprint、committed-but-unseen 与安全 replay；0057/0069 接管 stable result 和 binding exit；当前修订：ADR-0057 后继修订（current-state replay、持久 stale in-progress 与 reclaim 语义）：服务端 mutation 的 idempotency key、principal binding、事务 claim、结果 envelope 与 retention | amended-by 0041; amended-by 0042 |
| [0039](../DECISIONS/0039-adr-implementation-calibration.md) | superseded | implemented | stale | 历史 ADR 手工校准机制；当前状态分层与机器投影由 0056/0065 取代 | — |
| [0040](../DECISIONS/0040-outbox-subresource-target-and-child-undo.md) | accepted | partial | unverified | 子资源 intent 锚定 parent aggregate/CAS；撤销改为显式 compensation、残余副作用与 rebuild，由 0069/0073 收紧 | refines 0038 |
| [0041](../DECISIONS/0041-postgresql-engine-migration.md) | accepted | nonconformant | failed | PostgreSQL-only 与 row_version 仍有效；schema lifecycle 由 0067、容量与任务由 0072 裁决 | amends 0016; amends 0038 |
| [0042](../DECISIONS/0042-offline-availability-and-request-idempotency.md) | accepted | nonconformant | failed | ADR-0042 未被后继关系覆盖的 declared_current_scope：outbox intent key、fingerprint、committed-but-unseen 与安全 replay；0057/0069 接管 stable result 和 binding exit；当前修订：ADR-0057 后继修订（current-state replay、持久 stale in-progress 与 reclaim 语义）：服务端 mutation 的 idempotency key、principal binding、事务 claim、结果 envelope 与 retention | amends 0038; amended-by 0057 |
| [0043](../DECISIONS/0043-tag-management.md) | accepted | implemented | unverified | 标签 rename/delete/merge 的事实边界与 CAS；表结构不冻结，并补补偿、ABA、恢复与 mixed-version | — |
| [0044](../DECISIONS/0044-android-string-resourcing.md) | accepted | implemented | unverified | Android 用户可见字符串外置到 strings.xml；只做资源化，不虚构第二语言或领域规则 | — |
| [0045](../DECISIONS/0045-csrf-signing-key.md) | accepted | nonconformant | failed | ADR-0045 未被后继关系覆盖的 declared_current_scope：持久随机 CSRF/session key 与 placeholder fail-closed；restore/clone/identity 生命周期由 0059/0068 收紧；当前修订：ADR-0059 后继修订（per-install signing key 的 restore/clone 身份、首次生成与轮换边界）：数据库内 key、bearer/one-shot、operator override、recovery root 在 same-install restore 与 independent clone 中的生命周期 | amended-by 0059 |
| [0046](../DECISIONS/0046-android-recurring-reminder-detection-source.md) | accepted | nonconformant | failed | ADR-0046 未被后继关系覆盖的 declared_current_scope：WorkManager 仅作持久 best-effort 检测器；投递 outcome、single-flight 与非 exactly-once 语义由 0058 收紧；当前修订：ADR-0058 后继修订（同一 reminder key 只提醒一次的绝对表述）：Android recurring reminder 的 single-flight、publish outcome、completed dedupe 与稳定通知身份 | amended-by 0058 |
| [0047](../DECISIONS/0047-bundled-installer-windows-services.md) | accepted | nonconformant | failed | ADR-0047 未被后继关系覆盖的 declared_current_scope：Windows SCM/虚拟账户/ProgramData/loopback 仅是宿主 adapter；生命周期、bootstrap、provenance 分别由 0062–0064 接管；当前修订：ADR-0062 后继修订（安装数据/升级、启动验收和生命周期实施叙述）：ADR-0062 未被后继关系覆盖的 declared_current_scope：Windows 安装/升级/修复/卸载生命周期；main 基线未实现，installer overlay 仍有未持久化复制边界和非原子恢复标记；当前修订：ADR-0074 后继修订（installer recovery latch 的机器权限域、原子发布、迁移与前滚 repair）：ADR-0074 未被后继关系覆盖的 declared_current_scope：Windows 正式安装、修复、升级中的 lifecycle identity、owner handoff、installer recovery latch、runtime guard、委托操作租约、legacy 状态迁移、发布审计基线与未来宿主拓扑扩展边界；当前修订：ADR-0076 后继修订（ADR-0074-C01 至 C03 的 owner handoff 内容、单文件状态机与 legacy 协议退役语义）：正式 Windows Inno 首装、repair、跨 release 同事务恢复、installation owner claim、pairing-only handoff、Desktop Manager 首次绑定、旧 owner handoff 审计与统一失败证据；ADR-0063 后继修订（owner bootstrap secret 的一次性/可恢复语义和安装交接）：ADR-0063 未被后继关系覆盖的 declared_current_scope：main 未实现；overlay 已有 HMAC/DB 锁/listener recovery/handoff，但精确恢复、并发撤销、凭证解耦和 handoff 父目录 ACL 审查失败；当前修订：ADR-0074 后继修订（owner handoff 父目录权限、pending/confirmed 原子转换、完成页清理与中断接管）：ADR-0074 未被后继关系覆盖的 declared_current_scope：Windows 正式安装、修复、升级中的 lifecycle identity、owner handoff、installer recovery latch、runtime guard、委托操作租约、legacy 状态迁移、发布审计基线与未来宿主拓扑扩展边界；当前修订：ADR-0076 后继修订（ADR-0074-C01 至 C03 的 owner handoff 内容、单文件状态机与 legacy 协议退役语义）：正式 Windows Inno 首装、repair、跨 release 同事务恢复、installation owner claim、pairing-only handoff、Desktop Manager 首次绑定、旧 owner handoff 审计与统一失败证据；ADR-0076 后继修订（ADR-0063-C01 至 C06 在正式 Windows 安装器中的用户凭据派生、恢复与交接方式）：正式 Windows Inno 首装、repair、跨 release 同事务恢复、installation owner claim、pairing-only handoff、Desktop Manager 首次绑定、旧 owner handoff 审计与统一失败证据；ADR-0064 后继修订（构建 provenance、代码签名和未签名 Windows 验收叙述）：main 未实现；overlay 已有 staged inputs、固定 toolchain、真实 ISCC CI 和最终 hash，仍缺上游真实性、签名与 clean release/E2E | depends-on 0041; depends-on 0028; depends-on 0045; amended-by 0062; amended-by 0063; amended-by 0064 |
| [0048](../DECISIONS/0048-rive-mascot-animation.md) | rejected | not-started | stale | Rive 方案已拒绝且无代码消费者；仅保留历史，不得复活为实现债 | — |
| [0049](../DECISIONS/0049-debt-domain-contract.md) | accepted | nonconformant | failed | ADR-0049 未被后继关系覆盖的 declared_current_scope：Debt obligation 与 repayment/correction/forgiveness facts；身份依赖 0068，纯 fold/rebuild 由 0060/0073 收紧；当前修订：ADR-0060 后继修订（forgiveness 的 canonical/as-of fold 与 DebtVoid 灾难重建）：Debt 的 repayment、adjustment、forgiveness、void 余额 fold、终态与投影恢复 | depends-on 0001; depends-on 0068; depends-on 0027; depends-on 0029; depends-on 0038; depends-on 0041; depends-on 0042; amended-by 0060 |
| [0050](../DECISIONS/0050-android-baseline-profile-prerelease.md) | accepted | implemented | unverified | Baseline Profile 1.5.0-alpha06 仅为构建/测试期有限例外；稳定版可用即复审退出 | depends-on 0009; depends-on 0010; informational 0011 |
| [0051](../DECISIONS/0051-unified-recycle-bin.md) | accepted | partial | unverified | 回收站是带 OCC/retention 的用户恢复状态，不等于隐私擦除、备份 purge 或财务冲正；0073 refine | refines 0038 |
| [0052](../DECISIONS/0052-master-delete-recycle-bin-scope.md) | accepted | partial | unverified | 删除 master/catalog 不改写历史事实；在线删除、审计保留、备份擦除和恢复副本语义由 0073 收紧 | refines 0051 |
| [0053](../DECISIONS/0053-merchant-catalog-contract.md) | accepted | implemented | unverified | merchant catalog CRUD/recycle/alias 不改写历史账单，目录不是金额或账务事实真源 | refines 0052 |
| [0054](../DECISIONS/0054-merchant-catalog-merge-rename.md) | accepted | partial | unverified | merchant rename/merge 使用双 OCC 与显式 alias policy；不可逆影响、unmerge 和旧 outbox 冲突由 0073 收紧 | refines 0053 |
| [0055](../DECISIONS/0055-android-chart-native-canvas-tokens.md) | accepted | implemented | unverified | Android 图表使用原生 Canvas 与 design token；作为只读投影，失败不改变账本事实 | supersedes 0025 |
| [0056](../DECISIONS/0056-adr-lifecycle-current-state-ledger.md) | superseded | implemented | stale | 仅保留历史真实性原则；双状态账本和旧 registry 机制已由 0065 取代 | supersedes 0039; informational 0065 |
| [0057](../DECISIONS/0057-idempotency-stable-result-and-single-transaction-claim.md) | accepted | nonconformant | failed | 服务端 mutation 的 idempotency key、principal binding、事务 claim、结果 envelope 与 retention | amends 0042 |
| [0058](../DECISIONS/0058-recurring-reminder-delivery-semantics.md) | accepted | nonconformant | failed | Android recurring reminder 的 single-flight、publish outcome、completed dedupe 与稳定通知身份 | amends 0046 |
| [0059](../DECISIONS/0059-persisted-secret-restore-and-clone-identity.md) | accepted | nonconformant | failed | 数据库内 key、bearer/one-shot、operator override、recovery root 在 same-install restore 与 independent clone 中的生命周期 | amends 0045 |
| [0060](../DECISIONS/0060-debt-forgiveness-fold-calibration.md) | accepted | nonconformant | failed | Debt 的 repayment、adjustment、forgiveness、void 余额 fold、终态与投影恢复 | amends 0049 |
| [0061](../DECISIONS/0061-home-currency-minor-unit-semantics.md) | accepted | nonconformant | failed | ADR-0061 未被后继关系覆盖的 declared_current_scope：home-currency identity、minor-unit exponent、rounding、跨端 capability 与 FX snapshot；当前修订：ADR-0075 后继修订（C02/C03 全量持久绑定未落地期间的最小写时桥接门；不替代版本化绑定行与修订握手）：currency_binding_drift 写时门（debt/proposal/expense 盖章入口）、读路径降级分工、与全量持久绑定的边界 | amends 0001; amends 0027; amended-by 0075 |
| [0062](../DECISIONS/0062-windows-installer-lifecycle-transaction.md) | accepted | nonconformant | failed | ADR-0062 未被后继关系覆盖的 declared_current_scope：Windows 安装/升级/修复/卸载生命周期；main 基线未实现，installer overlay 仍有未持久化复制边界和非原子恢复标记；当前修订：ADR-0074 后继修订（installer recovery latch 的机器权限域、原子发布、迁移与前滚 repair）：ADR-0074 未被后继关系覆盖的 declared_current_scope：Windows 正式安装、修复、升级中的 lifecycle identity、owner handoff、installer recovery latch、runtime guard、委托操作租约、legacy 状态迁移、发布审计基线与未来宿主拓扑扩展边界；当前修订：ADR-0076 后继修订（ADR-0074-C01 至 C03 的 owner handoff 内容、单文件状态机与 legacy 协议退役语义）：正式 Windows Inno 首装、repair、跨 release 同事务恢复、installation owner claim、pairing-only handoff、Desktop Manager 首次绑定、旧 owner handoff 审计与统一失败证据 | amends 0047; depends-on 0041; informational 0006; amended-by 0074 |
| [0063](../DECISIONS/0063-recoverable-owner-bootstrap-ceremony.md) | accepted | partial | failed | ADR-0063 未被后继关系覆盖的 declared_current_scope：main 未实现；overlay 已有 HMAC/DB 锁/listener recovery/handoff，但精确恢复、并发撤销、凭证解耦和 handoff 父目录 ACL 审查失败；当前修订：ADR-0074 后继修订（owner handoff 父目录权限、pending/confirmed 原子转换、完成页清理与中断接管）：ADR-0074 未被后继关系覆盖的 declared_current_scope：Windows 正式安装、修复、升级中的 lifecycle identity、owner handoff、installer recovery latch、runtime guard、委托操作租约、legacy 状态迁移、发布审计基线与未来宿主拓扑扩展边界；当前修订：ADR-0076 后继修订（ADR-0074-C01 至 C03 的 owner handoff 内容、单文件状态机与 legacy 协议退役语义）：正式 Windows Inno 首装、repair、跨 release 同事务恢复、installation owner claim、pairing-only handoff、Desktop Manager 首次绑定、旧 owner handoff 审计与统一失败证据；ADR-0076 后继修订（ADR-0063-C01 至 C06 在正式 Windows 安装器中的用户凭据派生、恢复与交接方式）：正式 Windows Inno 首装、repair、跨 release 同事务恢复、installation owner claim、pairing-only handoff、Desktop Manager 首次绑定、旧 owner handoff 审计与统一失败证据 | amends 0047; depends-on 0028; depends-on 0045; amended-by 0074; amended-by 0076 |
| [0064](../DECISIONS/0064-windows-installer-build-provenance.md) | accepted | partial | unverified | main 未实现；overlay 已有 staged inputs、固定 toolchain、真实 ISCC CI 和最终 hash，仍缺上游真实性、签名与 clean release/E2E | amends 0047; depends-on 0010; depends-on 0062 |
| [0065](../DECISIONS/0065-executable-architecture-contract-governance.md) | accepted | partial | unverified | ADR 元数据、生成视图、历史/校准分离、稳定 clause 与最小 ratchet；证据自动化延后 | supersedes 0056 |
| [0066](../DECISIONS/0066-family-financial-fact-system-boundary.md) | accepted | partial | unverified | 领域核心、八个承重域、当前 Windows 单机拓扑与未来宿主/客户端扩展缝 | supersedes 0017; refines 0024; refines 0041 |
| [0067](../DECISIONS/0067-postgresql-schema-lifecycle-and-rollback.md) | accepted | nonconformant | failed | PostgreSQL 权威账本的首次建库、schema 升级、mixed-version、应用回退、数据库恢复和未来宿主适配；不再沿用 SQLite 文件切换协议 | supersedes 0031; refines 0041; refines 0066; depends-on 0062 |
| [0068](../DECISIONS/0068-family-identity-rbac-and-trust-boundaries.md) | accepted | nonconformant | failed | Account/Ledger/Member/Device/session/UploadLink/Web/Owner Console/admin/recovery 的授权与生命周期 | supersedes 0022; refines 0028; refines 0045; refines 0059; refines 0063 |
| [0069](../DECISIONS/0069-offline-intent-binding-and-protocol-evolution.md) | accepted | nonconformant | failed | Android Room confirmed cache/outbox、账本或会话切换、离线 mutation 重放、mixed-version API 与客户端 schema 演进；不引入 peer-to-peer 或 CRDT | refines 0038; refines 0042; refines 0057; refines 0061; refines 0066 |
| [0070](../DECISIONS/0070-accounting-time-and-calendar-binding.md) | accepted | nonconformant | failed | Expense/导入/OCR/通知的时间输入、ledger timezone revision、统计归属、DST 与 mixed-version | supersedes 0002; refines 0061; refines 0066; depends-on 0067 |
| [0071](../DECISIONS/0071-receipt-asset-authority-and-recovery.md) | accepted | nonconformant | failed | 收据原图上传、受保护读取、清理、完整性巡检、备份恢复和本地文件到未来对象存储的迁移 | refines 0003; refines 0059; refines 0066; depends-on 0067 |
| [0072](../DECISIONS/0072-postgresql-capacity-backpressure-and-task-execution.md) | accepted | nonconformant | failed | 查询/连接/资源预算、用户长任务、OCR/导入/维护背压、重启恢复和未来多实例门 | supersedes 0016; supersedes 0030; refines 0066; depends-on 0067 |
| [0073](../DECISIONS/0073-financial-facts-corrections-and-projections.md) | accepted | nonconformant | failed | Expense、明细、分摊、FX、账务日期、退款/拒付/冲正、Debt 事实 fold、预算/目标计划、回收与隐私擦除 | refines 0001; refines 0027; refines 0029; refines 0035; refines 0015; refines 0036; refines 0037; refines 0049; refines 0051; refines 0052; refines 0060; refines 0061; refines 0066; refines 0070 |
| [0074](../DECISIONS/0074-windows-installer-state-authority-and-owner-handoff.md) | accepted | partial | unverified | ADR-0074 未被后继关系覆盖的 declared_current_scope：Windows 正式安装、修复、升级中的 lifecycle identity、owner handoff、installer recovery latch、runtime guard、委托操作租约、legacy 状态迁移、发布审计基线与未来宿主拓扑扩展边界；当前修订：ADR-0076 后继修订（ADR-0074-C01 至 C03 的 owner handoff 内容、单文件状态机与 legacy 协议退役语义）：正式 Windows Inno 首装、repair、跨 release 同事务恢复、installation owner claim、pairing-only handoff、Desktop Manager 首次绑定、旧 owner handoff 审计与统一失败证据 | amends 0062; amends 0063; depends-on 0065; refines 0066; informational 0006; amended-by 0076 |
| [0075](../DECISIONS/0075-currency-binding-write-drift-gate.md) | accepted | implemented | verified | currency_binding_drift 写时门（debt/proposal/expense 盖章入口）、读路径降级分工、与全量持久绑定的边界 | amends 0061; depends-on 0061 |
| [0076](../DECISIONS/0076-windows-installation-owner-pairing-and-protocol-retirement.md) | accepted | partial | unverified | 正式 Windows Inno 首装、repair、跨 release 同事务恢复、installation owner claim、pairing-only handoff、Desktop Manager 首次绑定、旧 owner handoff 审计与统一失败证据 | amends 0063; amends 0074; depends-on 0062; depends-on 0065; refines 0068 |
<!-- ADR_STATUS_TABLE_END -->

## 当前需闭环的实施风险

这些是状态，不是要求把代码回滚到旧 ADR：

1. **P1 / 0041**：existing DB 的 backup 必须早于任何 `Base.metadata.create_all()`/DDL；随后只由
   Alembic 升级。
2. **P1 / 0042 + 0057**：持久化最小首次成功结果、绑定 original principal 并在 HIT 重做当前授权、
   删除非原子 stale reclaim，补 server key sweep 和 PG/Android 第三方插写测试；同事务 claim 基础保留。
3. **P1 / 0045 + 0059**：恢复后默认撤销所有 bearer/一次性授权；clone sanitation 必须同时覆盖
   `Invitation`、DB token 和 operator env secret，并补多进程原子 key get-or-create。
4. **P1 / 0060**：补 `Debt + DebtVoid` projection-loss rebuild 与 repay/adjust/forgive 并发回归，防止
   已作废债务在恢复后复活。
5. **P1 / 0061**：原子持久化 installation-global home-currency binding；配置漂移启动 fail closed；建立
   versioned capability/outbox/min-client gate，以及 backend/Android/Web/CSV 共享 0/2/3 exponent contract。
6. **P2 / 0046 + 0058**：engine single-flight、publish 显式 outcome 和 notification only-alert-once；
   稳定 tag/id 已有基础，`next_expected_date` 自动推进仍是独立准确性债。
7. **P2 / 0029**：邀请可以在 accept 时判过期，但后台 expiry 状态 sweep 尚未接入 scheduler。
8. **P2 / 0051**：30 天 purge scheduler 默认未启用，部分 master restore 尚缺可比较的删除代次/CAS。

## 尚需独立决策、不能在本次治理 ADR 中偷定的事项

- v1.x 无前缀 API 的兼容窗口、最低客户端版本和未来 `/api/v2` 触发条件；
- UploadLink URL-path credential 向 header/短期一次性凭证的兼容迁移；
- 本机磁盘、数据库 dump 和异地备份的数据静态加密威胁模型；
- 安装器发布、回滚、签名和网络拓扑继续在其独立工作流处理，本分支不混入。
