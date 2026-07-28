+++
schema_version = 2
id = "0075"
title = "写时币种绑定 drift 门（ADR-0061 C02/C03 桥接）"
summary = "持久版本化绑定落地前，写入口以 env 盖章新事实前校验与已持久事实的 home_currency_code 一致，漂移 fail closed"
current_scope = "currency_binding_drift 写时门（debt/proposal/expense 盖章入口）、读路径降级分工、与全量持久绑定的边界"
date = "2026-07-28"
decision_status = "accepted"
implementation_status = "implemented"
verification_status = "verified"
decision_type = "domain"
risk_level = "high"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "金额、FX 与跨端协议维护者"
verification_owner = "独立财务正确性 reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0061"
scope = "C02/C03 全量持久绑定未落地期间的最小写时桥接门；不替代版本化绑定行与修订握手"

[[relations]]
kind = "depends-on"
target = "0061"
scope = "home currency 语义身份与 fail-closed 原则来自 0061 C01-C03"
+++
# 0075 写时币种绑定 drift 门（ADR-0061 C02/C03 桥接）

## [ADR-0075-SCOPE] Context, Scope and Non-goals

PR#255 复评（2026-07-28 bot P1）：Android 空账本放行依赖服务端列表信封的安装级 currency capability，而该值取自请求时态 env（`FX_HOME_CURRENCY_CODE`）——纯 CNY 事实的安装改 env 为 JPY 后，信封告 JPY，首笔 JPY 欠款会与 CNY 事实并存污染；list→create 间重启构成陈旧能力 TOCTOU。本 ADR 固定**写时桥接门**这一最小落地：不接受 env 作为可信绑定，写时以持久事实为准。Non-goals：持久版本化绑定行、binding revision、跨端修订握手、漂移存量的治理——全部为 [[0061]] C02/C03 全量答案，归后续 0061 parity 切片（bot 该评论作为其紧迫性实证留档）。

## [ADR-0075-ASSUMPTIONS] Assumptions and Applicability

- 当前 home currency 是 installation-global（env 配置），所有 ledger 共享；持久事实的 `home_currency_code` 由写时 env 盖章冻结。
- 门运行在单写事务内；多实例并发不同 env 的交错写入不在本门防御面（见 [ADR-0075-C03]）。
- 存量安装（已含事实）与全新安装（空库）都适用；空库首笔即 claim binding。

## [ADR-0075-DRIVERS] Decision Drivers

- 未知/漂移币种下的金额写入必须 fail closed（0061 C01/C03：禁默认-CNY 猜测、禁热切换），100× 资损不可接受。
- 不接受请求时态 env 作为可信绑定：写时唯一可得的诚实参照是已持久事实自身。
- 最小侵入：不迁移、不改 schema、不引入修订握手（全量方案归 [[0061]] 后续切片）。

## [ADR-0075-ALTERNATIVES] Alternatives

- **A. 立即落持久版本化绑定行 + revision 握手**：ADR-0061 C02/C03 全量答案，但跨端（Android/Web/CSV）协议与迁移面远超 PR#255 范围，拒绝本轮内嵌，归后续 0061 parity 切片。
- **B. 信封 capability 从全库事实 distinct 推导而非 env**：把读路径也耦合到全表扫描，且混币存量下无单一答案（需额外裁决语义）；写时门已覆盖其风险面，拒绝。
- **C. 写时一致性校验（env vs 已持久事实）**：选定——零迁移、fail closed、与 record 冻结语义正交。
- **D. 把门放进共享冻结函数 `freeze_home_amount`**：误伤 `record_repayment`（金额继承 parent Debt 冻结币种、env 读值被丢弃），破坏既有「record 冻结币种优先」契约，拒绝（见 [ADR-0075-C02] 非落点）。

## [ADR-0075-DECISION] Decision

### [ADR-0075-C01] 写入口一致性校验，漂移 fail closed

任何以 env 币种盖章新事实的写入口，先校验 env 值与全库已持久事实（debts / expenses / member_repayment_proposals；repayments 继承 parent debt 冻结口径不重复查）的 `home_currency_code`：空库放行（首笔 claim binding）；全一致放行；任一不一致 = 配置漂移（0061 C02 声明不可热切换），拒绝写入 `currency_binding_drift`（409）。共享实现 `app/services/currency_binding_service.py::assert_currency_binding_consistent`。

### [ADR-0075-C02] 落点与明确的非落点

落点（以 env 盖章新事实的入口）：`debt_service._create.create_debt`、`debt_service._proposal.create_repayment_proposal`（proposal 行按 env 盖章，漂移即造出 proposal/debt 异币种错配实例）、`exchange_rate_service.apply_currency_payload`（expense confirm/manual/edit/CSV 统一口径，且会重盖章存量行）、`expense_service._create.create_pending_expense`（pending 行即成持久事实）。非落点：`record_repayment`——Repayment 表无 `home_currency_code` 列，金额语义继承 parent Debt 冻结币种，env 读值被丢弃，存量欠款的还款不受 env 漂移影响（既有「record 冻结币种优先」契约保持）；`create_bill_split_debt`——按邀请快照冻结而非 env；**纯元数据写**（R10② scope 精化：`apply_currency_payload` 中 `has_original_fields=false 且 amount_was_explicit=false` 的调用不碰任何币种快照，门与 env 读一并跳过——漂移/配错的 env 不得拖死 note/category/tags 维护；显式金额分支同样盖章 `home_currency_code=home`，仍在门内）；读路径不走此门：列表信封 capability 在 env 配错时降级 null（PR#255 R8-3），客户端对 null fail closed。批量写路径（R10①：CSV `_apply.apply_csv_import_batch`、legacy `import_service.import_rows`）在**批首**校验一次，行内经 `binding_checked=True` 跳过 per-row 门，避免每行 3 次全表 distinct（≤1000 行批次退化为数千次扫描）。

同源通知捕获契约门（R10③ / R11 / R12-A,E，声明单位门的两形态）：repayment 通知草稿**无条件**拒绝非 CNY 安装捕获（`repayment_draft_currency_unsupported`——repayment 捕获载荷没有 original 字段通道），R12-A 起叠加本 drift 门（双门交集：CNY 门挡解析器声明单位，drift 门挡 env 与事实漂移——JPY 事实 + env 漂回 CNY 同样拒捕）；expense 通知草稿为**条件门**（`notification_draft_currency_unsupported`）——仅当 payload 无**成对完整**的 original 币种+金额字段（R12-E 硬化：仅其一的残缺 FX 载荷按无 original 处理，CNY 下行为与 main 一致）时拒绝，成对显式 FX 捕获放行（`apply_currency_payload` 的 original 分支本就诚实换算）。两者的共同前提：Android 通知解析器按 CNY 分声明 `amount_cents`（无 FX 路径），env 章不代表该整数单位；跨币种捕获全量契约（原始币种字段 + 权威换算 + UX）挂账 D9。

R12 门族扩展：①**批量边界一次校验**（见上 R10①）；②**record_repayment 外币路径按笔拒**（R12-C：payload 带 original 币种字段且 parent Debt 冻结币种 ≠ env 时——换算口径（env）与折叠口径（debt）错位——按 `currency_binding_drift` 拒；无 original 字段的整数透传维持 record 冻结语义豁免不动，原「豁免」论证被 bot 证伪的部分以此精化为准）；③**无绑定金额行视为存量事实**（R12-F：三表皆空但存在无币种列的遗留金额行——Budget / Goal / MonthlyIncomePlan / RecurringItem（CNY 时代整数，单位不可判定）——且 env≠CNY 时，不得视为空库放行首笔绑定 → `currency_binding_unresolved`（409）；env==CNY 放行，多币种未发布、存量无绑定行定义上即 CNY 分；有绑定事实时仅按三表门裁决不重复触发）；④**goal/income 写面取同一信封 capability**（R12-D：Android 三处写面——goal 新建/编辑、收入计划——经列表信封 capability 严格解析，未知/不支持 → 禁写+明示文案，不再落 `FxContract.HomeCurrency` 兜底）。

### [ADR-0075-C03] 已知边界

本门不防多实例并发不同 env 的 TOCTOU 竞争（写时校验只认写时事实，不防两进程交错），不治理漂移已发生后的存量混币；两者均属版本化绑定的管辖范围，见 [[0061]] C02/C03 与 [ADR-0075-SCOPE] 的分工声明。

## [ADR-0075-CONSEQUENCES] Consequences

- Good：env 改配/漂移后的首笔写入被拒，JPY/KRW/VND 等零小数安装不再被信封广告误导放行；proposal/debt 异币种错配实例在创建侧绝源。
- Costs：每次盖章写多 3 次 distinct 查询（可忽略）；存量混币安装的**一切**盖章写被锁死，必须先修复配置或数据（fail closed 的既定代价）。
- Limits：TOCTOU 与存量混币治理仍待版本化绑定（[ADR-0075-C03]）。

## [ADR-0075-REVERSIBILITY] Reversibility, Replacement and Retirement

纯增量防线：移除门即回到既有行为，无 schema/协议变更。持久版本化绑定（[[0061]] C02/C03 后续切片）落地后，本门应由绑定行校验替代，届时按该切片决策退役本桥接（保留 `currency_binding_drift` 错误码或其修订语义，避免客户端映射漂移）。

## [ADR-0075-EVIDENCE] Verification and Evidence

- `backend/tests/test_debt_binding_drift.py`：env 改 JPY 后首笔 debt 创建 → 409 `currency_binding_drift`；空库放行；全一致放行；expense 事实漂移经 service 级断言拒绝；env 配错（非支持集码）维持 `currency_not_supported` fail-fast 先于门；R10② 纯元数据 payload 在配错 env 下不过门不读 env、显式金额 payload 仍 409；R10① `binding_checked=True` 跳过 per-row 门（批首职责）；R10③ repayment 草稿非 CNY 拒建。
- R11 expense 通知草稿条件门（`backend/tests/test_notification_drafts.py`）：非 CNY + 无 original 字段 → 422 `notification_draft_currency_unsupported`；非 CNY + original 字段（JPY↔JPY base 通道）→ 放行且 1:1 诚实换算；CNY 放行由既有 capture 钉保持。
- R12（`backend/tests/test_debt_binding_drift.py` + Android VM 测试）：repayment 草稿 CNY 门 + drift 门交集（JPY 事实 + env 漂回 CNY → 409 drift）；record_repayment 外币路径按笔拒（JPY debt + env CNY + original 字段 → drift；matching 三方一致放行；无 original 透传放行）；R12-E 残缺 FX 载荷非 CNY 拒、CNY 行为与 main 一致；R12-F 仅无绑定金额行 + env≠CNY → `currency_binding_unresolved`、env==CNY 放行、有绑定事实走既有 drift 门；R12-D 三个 Android 写面（goal 新建/编辑、收入计划）取信封 capability 解析（JPY "1200" → 1200 minor），capability 未知/不支持 → 禁写+明示文案。
- R12-B（Android `ExpenseSearchTest`）：未知 home 码行 raw-minor 只比 home 双腿，已知 original 币种继续按其声明解析匹配（VND-home/USD-original 双路可达）。
- 既有 `test_web_debt_currency_actions.py`（env 切换后按 record 冻结币种行动作）保持绿——证明 `record_repayment` 非落点语义未回退。
- Android 客户端不经新映射：AppError JSON 的 `message` 字段经 `backendErrorUserMessage` 通用兜底原样呈现。

## [ADR-0075-REFERENCES] References

- [[0061]]：home currency 语义身份、fail-closed 原则与全量持久绑定目标（本 ADR amends/depends-on 的对象）。
- [[0027]]：后端权威 FX 与 snapshot；本门不改变 record 冻结语义。
- `app/services/currency_binding_service.py`、`backend/tests/test_debt_binding_drift.py`：本决策的实现与钉。
