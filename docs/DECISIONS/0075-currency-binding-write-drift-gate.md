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

落点（以 env 盖章新事实的入口）：`debt_service._create.create_debt`、`debt_service._proposal.create_repayment_proposal`（proposal 行按 env 盖章，漂移即造出 proposal/debt 异币种错配实例）、`exchange_rate_service.apply_currency_payload`（expense confirm/manual/edit/CSV 统一口径，且会重盖章存量行）、`expense_service._create.create_pending_expense`（pending 行即成持久事实）。非落点：`record_repayment`——Repayment 表无 `home_currency_code` 列，金额语义继承 parent Debt 冻结币种，env 读值被丢弃，存量欠款的还款不受 env 漂移影响（既有「record 冻结币种优先」契约保持）；`create_bill_split_debt`——按邀请快照冻结而非 env。读路径不走此门：列表信封 capability 在 env 配错时降级 null（PR#255 R8-3），客户端对 null fail closed。

### [ADR-0075-C03] 已知边界

本门不防多实例并发不同 env 的 TOCTOU 竞争（写时校验只认写时事实，不防两进程交错），不治理漂移已发生后的存量混币；两者均属版本化绑定的管辖范围，见 [[0061]] C02/C03 与 [ADR-0075-SCOPE] 的分工声明。

## [ADR-0075-CONSEQUENCES] Consequences

- Good：env 改配/漂移后的首笔写入被拒，JPY/KRW/VND 等零小数安装不再被信封广告误导放行；proposal/debt 异币种错配实例在创建侧绝源。
- Costs：每次盖章写多 3 次 distinct 查询（可忽略）；存量混币安装的**一切**盖章写被锁死，必须先修复配置或数据（fail closed 的既定代价）。
- Limits：TOCTOU 与存量混币治理仍待版本化绑定（[ADR-0075-C03]）。

## [ADR-0075-REVERSIBILITY] Reversibility, Replacement and Retirement

纯增量防线：移除门即回到既有行为，无 schema/协议变更。持久版本化绑定（[[0061]] C02/C03 后续切片）落地后，本门应由绑定行校验替代，届时按该切片决策退役本桥接（保留 `currency_binding_drift` 错误码或其修订语义，避免客户端映射漂移）。

## [ADR-0075-EVIDENCE] Verification and Evidence

- `backend/tests/test_debt_binding_drift.py`：env 改 JPY 后首笔 debt 创建 → 409 `currency_binding_drift`；空库放行；全一致放行；expense 事实漂移经 service 级断言拒绝；env 配错（非支持集码）维持 `currency_not_supported` fail-fast 先于门。
- 既有 `test_web_debt_currency_actions.py`（env 切换后按 record 冻结币种行动作）保持绿——证明 `record_repayment` 非落点语义未回退。
- Android 客户端不经新映射：AppError JSON 的 `message` 字段经 `backendErrorUserMessage` 通用兜底原样呈现。

## [ADR-0075-REFERENCES] References

- [[0061]]：home currency 语义身份、fail-closed 原则与全量持久绑定目标（本 ADR amends/depends-on 的对象）。
- [[0027]]：后端权威 FX 与 snapshot；本门不改变 record 冻结语义。
- `app/services/currency_binding_service.py`、`backend/tests/test_debt_binding_drift.py`：本决策的实现与钉。
