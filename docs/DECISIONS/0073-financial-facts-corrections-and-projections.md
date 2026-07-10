+++
schema_version = 2
id = "0073"
title = "家庭财务事实、更正、冲正与投影契约"
summary = "区分建议、意图、计划、当前事实聚合、追加事实与投影，并为金额、更正、退款、债务重建和删除建立统一边界"
current_scope = "Expense、明细、分摊、FX、账务日期、退款/拒付/冲正、Debt 事实 fold、预算/目标计划、回收与隐私擦除"
date = "2026-07-11"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "domain"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "financial domain、PostgreSQL schema、API 与客户端维护者"
verification_owner = "独立财务正确性、迁移与恢复 reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "refines"
target = "0001"
scope = "整数金额从无 float 原则收紧为有界 signed 64-bit minor-unit、显式币种、统一取整与字段级符号语义"

[[relations]]
kind = "refines"
target = "0027"
scope = "FX 后端权威、原币/home snapshot 与退款等后续事实的独立换算时间点"

[[relations]]
kind = "refines"
target = "0029"
scope = "家庭分账接受时同事务创建 Expense、Debt、Claim 与审计的事实 bundle 和防重复语义"

[[relations]]
kind = "refines"
target = "0035"
scope = "ExpenseItem、折扣、税费、金额核对、人工 mismatch acknowledgement 与投影重建边界"

[[relations]]
kind = "refines"
target = "0015"
scope = "OCR/vision provider 只生成建议；原图 provider 的本地与远程信任边界必须显式决策"

[[relations]]
kind = "refines"
target = "0036"
scope = "Budget Advisor 结构化 allowlist 不得外推授权视觉 provider，provider egress 必须逐一裁决"

[[relations]]
kind = "refines"
target = "0037"
scope = "建议 provenance、模型/解析版本与用户 ownership 不能被后台覆盖"

[[relations]]
kind = "refines"
target = "0049"
scope = "Debt 母对象、追加事实、proposal 非事实、纯 fold、terminal void latch 与灾难重建"

[[relations]]
kind = "refines"
target = "0051"
scope = "回收、恢复、财务冲正和隐私擦除是不同状态转换"

[[relations]]
kind = "refines"
target = "0052"
scope = "删除 master/catalog 不得改写历史事实，事实 purge 也不得伪装成退款或冲正"

[[relations]]
kind = "refines"
target = "0060"
scope = "DebtForgiveness 纳入纯事实 fold，并从 DebtVoid 事实而非可变 status 重建 terminal latch"

[[relations]]
kind = "refines"
target = "0061"
scope = "所有财务对象共享 minor-unit carrier、入口上限、rounding、currency binding 和 overflow 规则"

[[relations]]
kind = "refines"
target = "0066"
scope = "家庭账务事实承重域内的事实分类、写权限、修订、补偿、恢复和故障隔离"

[[relations]]
kind = "refines"
target = "0070"
scope = "确认与更正事务必须同时冻结带 precision 的 event-time representation、accounting date 和 calendar revision"
+++
# 0073 家庭财务事实、更正、冲正与投影契约

## [ADR-0073-SCOPE] Context, Scope and Non-goals

小票夹已经是家庭账务事实系统，而不是把一张小票识别成一行金额的上传工具。一个家庭账本同时包含人工确认的
Expense、明细与分摊、债务和还款、预算与目标、OCR/AI 建议、离线意图、退款/拒付，以及可删除重建的统计投影。
这些对象如果都被叫作“记录”，就会产生几类实质错误：把 AI 建议当成事实，把未来计划计入余额，用负 Expense 或
折扣伪装退款，直接改写已确认交易而不留修订，把可变 `Debt.status` 当灾难恢复真相，或用删除代替现实资金冲正。

当前代码已有若干正确基础：PostgreSQL 是结构化业务权威，Expense/Debt 写入使用服务端权限和 `row_version`，Debt
还款、调整、还款作废与 forgiveness 使用追加行，OCR 不能确认 Expense。但当前金额仍落在 PostgreSQL `INTEGER`，
API parser 主要只有下限，Web 仍固定 `/100` 或 `Math.round`；confirmed Expense 可被原地 PATCH/REJECT 而没有统一
revision；没有退款/chargeback 事实；Debt 的 terminal void 重建仍读取可变 parent status。这些不是文档欠漂亮，而是
代码在溢出、审计、重建和跨端一致性上的已证实缺口。

本 ADR 决定财务对象类型、金额 carrier、确认/更正事务、后续资金事实、Debt fold、删除与恢复边界。它不要求把所有
Expense 改成 event sourcing，不引入复式记账总账或企业关账，不允许 AI 自动入账，也不借此实现证券、税务、银行对账
或多 active-writer 共识。收据 bytes 的权威和恢复由 [[0071]] 负责；本 ADR 只约束图片/建议如何关联财务事实。

## [ADR-0073-ASSUMPTIONS] Assumptions and Applicability

- PostgreSQL 是 confirmed 财务聚合、追加事实、权限、revision/audit 和投影 checkpoint 的唯一在线权威。
- 当前是一套 PostgreSQL、一个 active backend writer、多账本、多成员与可能长期离线的多客户端；客户端不能直写 DB。
- installation home-currency binding 当前沿用 [[0061]]；若未来改为 per-ledger，必须先迁移事实和离线 payload 语义。
- ledger calendar binding 和 accounting date 沿用 [[0070]]；设备/浏览器时区只影响展示，不能改变归属。
- 家庭用户允许更正自己确认过的事实；系统的目标是保留谁、何时、基于哪个版本、从什么改到什么，而不是假装事实永不出错。
- 金额规模以家庭场景为限，但 schema、parser、客户端和聚合必须在同一明确边界内工作，不能依赖“通常金额很小”。
- 图片、OCR provider、AI、后台投影和客户端都可能失败；这些失败不得自动创造、删除或覆盖 confirmed 财务事实。
- 未来若引入受监管总账、复式分录、关账或不可变法定审计，本 ADR 必须被更强模型 supersede，不能靠扩写 Expense 模拟。

## [ADR-0073-DRIVERS] Decision Drivers

- 同一金额跨 Android、Web、CSV、数据库、FX、退款、分摊和报表必须得到完全相同的整数与币种解释。
- 用户修订已确认事实需要可追责、可 OCC、可重试，但家庭应用不应为此承担全量 event sourcing 的运维和认知成本。
- 现实世界的新动作应新增事实；录入错误应修订已有聚合。两者不能用同一个“编辑金额”入口混淆。
- Debt 的余额和 terminal 状态必须能从最小事实集合纯重建，不能依赖碰巧还在的 response、cache 或 mutable projection。
- 建议、离线意图和计划有自身价值及权限，但都不能提前进入现金流、余额、预算消耗或还款事实。
- 删除、回收、冲正和隐私擦除具有不同用户意图、投影效果、恢复能力和备份后果，API/UX 必须明确命名。
- correctness 优先于兼容便利；旧客户端无法表达 revision/currency/calendar 语义时应保留意图并要求升级，而不是猜默认值。
- 投影可异步和可重建，但用户不能在没有 source revision/freshness 的情况下把 stale projection 当当前事实。

## [ADR-0073-ALTERNATIVES] Alternatives

### [ADR-0073-ALT-A] A. 所有财务对象继续使用可变 CRUD 行

拒绝。它实现便宜，却让退款、还款、forgiveness、void 和现实世界的先后动作丢失；删除或覆盖一行后无法证明余额为何变化。

### [ADR-0073-ALT-B] B. 所有领域对象改成全量 event sourcing

拒绝。它能统一历史，但会迫使普通备注、商家、分类和 UI 偏好都通过 replay 恢复，显著增加迁移、查询、快照、版本化和维护成本。
当前没有消费者证明这项复杂度值得承担。

### [ADR-0073-ALT-C] C. 当前事实聚合受控修订，独立经济动作使用追加事实，所有读模型都是投影

选定。Expense 仍以 current aggregate 为在线权威，但 confirmed 更正必须有 revision/audit/OCC；退款、chargeback settlement、
reversal、Debt repayment/adjustment/forgiveness/void 等独立动作追加事实；投影只从这些权威输入计算。

### [ADR-0073-ALT-D] D. 用负 Expense、负分摊、discount 或删除表达所有反向金额

拒绝。符号失去业务语义，gross/net、退款日期、FX 差异、原交易关联、重复提交与审计都无法可靠区分。

## [ADR-0073-DECISION] Decision

选择 C。系统以“当前事实聚合 + 有界 revision + 追加经济事实 + 可重建投影”作为家庭账务核心；对象分类、金额、事务、权限和
恢复规则如下，任何入口和客户端都不能另行解释。

### [ADR-0073-C01] 六类对象身份不得互换

| 身份 | 例子 | 是否权威 | 允许写入者 | 允许进入的投影 |
| --- | --- | --- | --- | --- |
| suggestion | OCR 字段、AI 预算建议、重复候选 | 只对“模型曾建议什么”有 provenance；不是财务真相 | provider adapter 经后端写 suggestion store | 否 |
| proposal / intent | outbox mutation、成员“我已还”proposal、待接受分账 | 对用户提交意图有权威；尚未被有权主体接受 | 已认证用户经后端/本地 intent store | 否 |
| plan | budget、goal、recurring schedule、还款计划 | 对未来计划本身有权威；不是已发生交易 | 获授权用户经 plan service + OCC | 否；只进入 plan/variance 投影 |
| current fact aggregate | confirmed Expense 及其 items/splits/FX/time snapshot | 当前确认版本是在线财务权威 | financial domain service，经权限、OCC、revision | 只进入其明确注册的 spending/gross 等 fold |
| append-only fact/event | refund、chargeback settlement、reversal、repayment、DebtAdjustment、forgiveness、void | 该独立动作一旦提交即为历史权威 | financial domain service，只追加；错误以新事实纠正 | 只按事件类型进入 net/cash/liability 等 fold |
| projection | 月报、余额、Debt status、items mismatch 状态、dashboard/cache | 否；可丢弃重建 | projector/rebuild worker 或只读 SQL | 不作为输入，只展示 fold 结果 |

“用户写的”不自动等于 financial fact，“机器写的”也不自动等于 projection。proposal 可以永久保存和审计，但在确认前不得改变余额；
plan 可以是用户权威意愿，但不得伪装成已支付；projection 即使存在于 PostgreSQL，也不能反向覆盖事实。

同一个事实进入哪个 fold 必须显式注册，不能以“都是财务事实”为由全部相加：

| 权威输入 | ledger spending | household consolidated spending | cash movement | liability balance | gross/refund/net |
| --- | --- | --- | --- | --- | --- |
| 普通 confirmed purchase Expense | 当前 ledger 计一次 | 按 household economic-event identity 计一次 | 仅凭 Expense 不证明账户现金移动 | 否 | gross purchase，net 初始同 gross |
| 跨账本 split/邀请生成的 receiver Expense | receiver ledger 计一次 | 与 source Expense 共享 origin identity，只合并一次 | 不因复制 Expense 再记一笔 | 单独 Debt fact 承担 | 不重复原购买 gross |
| Debt obligation | 否 | 否 | 否 | 增加/建立 liability | 否 |
| repayment / forgiveness / void / adjustment | 否 | 否 | 仅真实 repayment 可形成一次 transfer/cash movement；forgiveness/void 不得伪装付款 | 按类型折叠 liability | 否 |
| refund / chargeback / reversal | 不改写原 gross | 通过原 economic-event link 去重 | settled refund/chargeback 可形成一次反向 movement | 仅显式关联时影响 | typed event 改 net，gross 保留 |

跨账本 invitation/bill-split 必须保存稳定 `household_economic_event_id`（名称可迁移）和 source/receiver relation；在该身份与
投影版本落地前，家庭 consolidated spending 不得把多账本 Expense 简单求和。Debt repayment 改变负债并可表达一次资金移动，
不得再次计作购买支出。每个新事实类型若没有 projection matrix 和 double-count golden test，只能保持未注册/不进入投影。

### [ADR-0073-C02] Expense confirmation 形成一个原子财务 envelope

pending Expense 是可编辑草稿聚合；只有有权用户的 confirm command 才把它变为 current fact aggregate。确认必须在一个 PostgreSQL
事务内完成以下动作：锁定/校验 `row_version`、权限与 ledger binding；确定 canonical amount/currency/FX snapshot；冻结带 precision 与
source-zone/offset provenance 的 event-time representation（只有时刻可知时才是 instant）及 accounting date/calendar revision；校验
ExpenseItem、discount/tax/service fee 与 mismatch acknowledgement；校验 ExpenseSplit 和成员；
写 `confirmed_at`、首个 aggregate revision/audit；递增 `row_version`；写投影 invalidation/outbox。任一检查或写入失败则全部回滚。

图片 bytes 和 provider 调用不加入数据库事务；确认只关联由 [[0071]] 验证过的 asset identity/status。缺图可以阻止要求证据的确认或标记
明确的 evidence-missing 状态，但不能在 DB 提交后假装跨文件系统原子成功。后台 OCR/AI、清图或 thumbnail 失败不撤销已确认事实。

### [ADR-0073-C03] Confirmed Expense 更正使用 current revision，不强制全量 event sourcing

authorized correction command 必须携带 `expected_row_version`，服务端在同一事务写 current aggregate 和不可变 `ExpenseRevision`：至少记录
aggregate ID、before/after revision、actor/principal/device、命令/idempotency ID、changed field mask、旧/新 canonical value、server UTC、
用户原因或稳定 system reason，以及使用的 currency/calendar contract revision。event time 的旧/新值必须连同 representation、precision、
source zone/offset provenance 记录；date-only 不得在 correction 中被伪造成 instant。金额、币种、event time、accounting date、items、splits、
confirmed/recycle inclusion 等 materially financial 字段不得绕开此入口原地更新。

current Expense 行仍是在线权威；revision 是审计、冲突解释和受控恢复证据，不要求所有读取 replay 全部历史，也不得在未证明完整前把它
冒充唯一重建源。普通文字修正可以使用结构化 reason code；金额、币种、日期、分摊、confirmed 后 void/recycle 必须让用户看到影响范围。
后台 enrichment 只能更新 suggestion/provenance 或尚由自动化拥有的 pending 字段；confirmed 后没有用户 correction command 就不得改写。

`rejected` 只表示草稿未被接受。confirmed 事实不能直接改成 rejected；录错事实走 audited void/correction，现实资金反向走 linked fact，
用户暂时隐藏走 recycle。每条命令返回稳定 first-result envelope；committed-but-unseen 重试返回同一 revision/结果，不再执行一次。

### [ADR-0073-C04] 退款、拒付和冲正是关联事实，不是负 Expense

- confirmed purchase/Expense 的 principal magnitude 保持非负；discount 只表示同一购买内减少应付的小计，不能表示事后退款。
- partial/full refund 与 settled chargeback 使用正 magnitude 的 typed linked fact，引用原 Expense，保存自身发生时间、accounting date、
  original/home currency snapshot、actor/source、idempotency ID 和 revision。net projection 按 type 应用方向；gross purchase 保持可追踪。
- 累计有效 refund/chargeback principal 默认不得超过原 confirmed amount；手续费、利息、汇兑差异或额外赔付使用独立有类型事实，不能靠
  超额 refund 偷换。外币退款按退款自身发生时间冻结 FX，不自动复用购买日 rate。
- 错误 refund/chargeback 不删除、不改负数，追加指向原 event 的 reversal；一个 event 至多有一个 active reversal latch，重复请求稳定返回。
- 删除、recycle、reject、DebtAdjustment、负 discount 和普通 income 均不能代替 refund/chargeback/reversal。API/报表必须同时能解释 gross、
  refunded、net 和 effective accounting date，不能只给一个不可追溯的净额。

### [ADR-0073-C05] Debt 由母对象和追加事实纯重建

Debt parent 保存 obligation identity、ledger/participants、direction、frozen principal、currency/FX provenance、source 和创建时间；这些基础字段
不是余额投影。Repayment、RepaymentVoid、DebtAdjustment、DebtForgiveness 和 DebtVoid 是追加事实。MemberRepaymentProposal 只是 proposal，
只有有权 creditor confirm 后创建 Repayment 才进入 fold。

canonical fold 为：

```text
valid_repayments = Repayment where no active RepaymentVoid exists
paid = sum(valid_repayments.amount_minor)
remaining = principal_amount_minor
          + sum(DebtAdjustment.signed_amount_minor)
          - paid
          - sum(DebtForgiveness.amount_minor)
```

fold 对同一 committed fact set 必须纯、确定、与执行顺序无关；每次 fold-changing write 在 parent aggregate lock/CAS 内验证 `remaining >= 0`、
写 event、递增 parent revision 并提交。stored `Debt.status`、`remaining`、`paid`、goal progress 和 API response 都是 projection，禁止成为 fold 输入。

DebtVoid existence 是 terminal latch：一旦提交，后续 repayment/adjustment/forgiveness/proposal-confirm 必须 fail closed；重建只查 DebtVoid 事实就能
恢复 voided，不得依赖 mutable `Debt.status == 'voided'`。当前契约不支持 unvoid；若未来需要，必须新增有权限、原因、影响分析的 append fact ADR。

### [ADR-0073-C06] Items、splits、FX 与 accounting date 与聚合 revision 同事务

ExpenseItem 是 current aggregate 的组成部分，不是独立现金流；product/tax/service fee 为非负 magnitude，discount 为非正 magnitude。items sum、
Expense total 和 FX/home amount 使用同一 money arithmetic。`items_sum_status` 是投影；“用户已知仍确认 mismatch”是独立的人工决定输入，必须记录
actor/reason/revision，不能只把投影字符串改成 `mismatch_acknowledged` 后丢失来源。

ExpenseSplit 是同一 confirmed amount 的分配事实组成部分；active splits 必须引用同 ledger/授权成员。若产品选择全额分配，sum 必须精确等于可分摊总额；
若允许部分分配，必须把 residual/unassigned 作为显式语义和投影，不能让 mismatch 被当成完整分摊。跨账本邀请
接受产生的接收方 Expense、Debt/linkage 和 split 状态继续服从其领域事务，不得让客户端分别补写。修改 amount/items/splits/FX/event time 中任一项时，
同一 correction transaction 必须重校验并写新 aggregate revision、currency snapshot、accounting date 和 projection invalidation；不能留下“新总额 +
旧分摊”“新时间 + 旧月份”或“新原币 + 旧 home amount”。

### [ADR-0073-C07] 金额 carrier、上限、符号和取整全链路一致

- 所有 canonical money magnitude、signed adjustment、item、split、budget、goal、Debt 和 refund 字段在 PostgreSQL 使用 signed 64-bit `BIGINT`；
  `*_cents` 只是兼容名，语义是显式 currency 的 integer minor units。
- 单个用户/API 可提交金额统一满足 `abs(amount_minor) <= MAX_ABS_MONEY_MINOR`，本阶段常量为 `9_000_000_000_000`。backend schema、Pydantic、
  Android、Web、CSV/import 和离线 payload 使用同一机器契约与边界 fixture；不得每个 endpoint 自定上限。
- carrier 可表示负数不等于每个字段可为负：Expense principal/item product/split/Debt principal/repayment/refund magnitude 按领域要求非负或正；只有明确
  `signed adjustment`/discount 等字段允许负。用类型和 DB CHECK 表达，不靠调用方记忆。
- 所有加减乘、sum 和 FX 转换做 checked arithmetic。中间值使用 Decimal/NUMERIC；落 minor unit 使用 [[0061]] 的 currency exponent 和
  `ROUND_HALF_UP`。binary float/double、JavaScript `Number` 乘 100、模板固定 `/100` 或各端自己的 `Math.round` 不得产生权威金额。
- 在线 major-unit 输入优先提交规范 decimal string，由后端权威转换；离线 intent 保存原始 decimal/currency/binding revision，重放时由后端转换。
  客户端可预览，但服务端回执中的 minor amount 才能成为 confirmed value。若协议仍传 minor integer，客户端实现必须通过同一 golden vectors。
- 聚合可能超过单笔 cap；SQL sum 使用不会静默溢出的 NUMERIC/checked result，并在对外序列化前验证范围。溢出返回稳定错误并保持原事务未提交。

### [ADR-0073-C08] AI/OCR 永远只写 suggestion 和 provenance

OCR/AI/规则可以生成字段候选、置信度、模型/provider/algorithm version、输入 asset hash、生成时间和最小必要 source span。provider 不得写 confirmed
Expense、revision、refund、Debt event、plan confirmation 或 projection checkpoint；provider 回调只能交给 suggestion service。

用户采纳建议是显式命令：服务端展示 candidate 与当前 aggregate revision，用户确认/修改后再走 C02/C03。用户编辑字段后自动 ownership 终止；
re-OCR、重试、模型升级或后台批处理不得覆盖。已确认事实只可作为最小化、经权限允许的 provider 输入。当前收据/债务**原图** vision
provider 只允许明确配置的 local-loopback adapter；Budget Advisor 的结构化字段 allowlist 不授权任何视觉 provider。启用远程原图/附件 provider
前必须另有 accepted security/privacy 决策与用户知情，逐 provider 定义图像/字段处理、网络目的地、retention、训练用途、日志、撤销和失败降级；
实现 egress profile 只能证明符合该决定，不能由目录或 provider 注册本身创造授权。provider timeout、无结果、恶意输出或预算耗尽均降级为
手工路径，不改变事实。

### [ADR-0073-C09] 删除、回收、void、冲正和隐私擦除必须分离

| 操作 | 真实语义 | 财务投影 | 可恢复性 |
| --- | --- | --- | --- |
| reject pending | 草稿从未成为事实 | 从未进入 | 可按产品策略保留审计，不等于 confirmed undo |
| correction | 已确认事实录入有误 | 从新 revision 重算 | current 值可再次修订；历史 revision 保留 |
| void confirmed | 该记录不应作为有效事实，例如重复录入 | 从 active fold 排除，保留 void reason | terminal/恢复需显式新契约，不靠删行 |
| refund/chargeback/reversal | 现实世界发生新的反向经济动作 | gross 保留，net 按 linked fact 变化 | 以新 reversal fact 纠错 |
| recycle/archive | 用户可恢复地移出普通工作集 | inclusion 规则显式、恢复后精确回到原 revision | OCC + audit，可恢复 |
| privacy erase/purge | 明确删除 bytes/PII/事实的主权操作 | 影响必须预览并由用户确认 | 通常不可逆；备份残留和保留窗口必须披露 |

删除 catalog/category/merchant 等 master 继续不得批量重写历史 Expense。事实 purge 不能伪装成退款，也不能通过清除 revision/audit 伪造“从未发生”；
若隐私要求必须擦除明文，保留的最小 tombstone/erasure receipt 只能含完成证明和不可逆边界，不得保留本应删除的 PII。执行前说明 active data、图片、
AI/provider、日志与备份各自范围；部分完成进入可重入 recovery，不得显示“已全部删除”。

### [ADR-0073-C10] 写权限位于 domain service，客户端和投影均无裁决权

所有 confirm/correct/void/refund/reversal/debt-event/recycle/purge 命令在后端重新做 principal、ledger membership/capability、target ownership、state、
OCC、idempotency、currency/calendar revision 和 field invariant 校验。Android ViewModel/Repository、Web JS、owner UI、导入器、OCR provider、后台
projector 和数据库运维脚本不得绕开 service 复制状态转换。

member 只能改被授权账本和产品允许的自身/共同事实；ledger owner 的管理权不自动授权改写成员历史；maintainer/OS admin 能恢复系统，不应使用 SQL
替代普通业务命令。break-glass repair 必须有备份、scope、actor、dry-run、before/after hash、不可变 receipt 和复审；不能成为日常写入口。

### [ADR-0073-C11] Projection 有 source revision 和确定性重建协议

每个 materialized projection/cache 声明输入集合、fold/version、source watermark/revision、fresh/stale/failed 状态和重建 owner。读取不能仅因一行存在就
宣称 current；projection revision 落后时，按产品风险选择同步计算、明确 stale、只读或阻塞，不得把旧余额当新余额。

事实事务不等待昂贵全局重建，但必须在同一事务写 projection invalidation/outbox。projector 至少 once 执行且按 aggregate revision 幂等；旧 revision 不得
覆盖新 projection。单个账本/聚合失败隔离，不阻塞人工记账；队列有界并按 [[0072]] 背压。rebuild 从权威 current aggregates + append facts 开始，在 shadow
namespace/version 中校验行数、minor-unit totals、latches 和 hash，成功后原子切换。不得边 rebuild 边向用户混合新旧 version。

Debt disaster rebuild 必须忽略 stored status，重建 DebtVoid latch 和 canonical fold。Expense projection rebuild 使用 current aggregate revision；历史 revision
只作审计/校验，除非另有证据证明某个 projector 的完整 replay contract。

### [ADR-0073-C12] 失败矩阵是发布契约

| 失败 | 必须结果 | 禁止结果 |
| --- | --- | --- |
| stale `row_version` / binding revision | 409/稳定 conflict，返回可安全刷新信息，零事实/零 revision 变化 | last-write-wins |
| 金额越界、符号错误、Decimal/FX overflow | 422/fail closed，整个事务回滚 | DB 截断、wrap、float 近似 |
| items/splits/FX/accounting date 任一校验失败 | confirmed/correction 全回滚，保留原 revision | 部分新总额、旧分摊或旧月份 |
| revision/audit 插入失败 | current aggregate 不得提交 | “值改了但无历史” |
| response 丢失但事务已提交 | 同 idempotency key 返回第一次稳定 result/revision | 再建 refund、还款或 correction |
| refund/reversal 重复或越额 | 返回既有结果或稳定 conflict | 生成第二笔净额变化 |
| AI/OCR/provider 失败或恶意输出 | suggestion failed/ignored，手工路径可用 | confirmed fact 被改写 |
| projection worker 崩溃/积压 | authority 已提交、投影明确 stale/可重建并背压 | 回滚已提交事实或显示旧值为 current |
| Debt stored status 与 facts 冲突 | facts 胜出、告警并重建；DebtVoid existence 保持 terminal | 从 status 猜 event 或复活 Debt |
| 图片丢失 | 财务事实保持、asset integrity 标缺失并进入 [[0071]] repair | 删除/清理财务事实或伪造 image-deleted |
| 旧客户端缺 contract capability | `upgrade_required`/只读/review，离线 intent 保留 | 默认 CNY、默认日期、丢 intent |
| privacy purge 中断 | receipt 显示 partial、可重入续作、未删范围可见 | 宣称 complete 或自动扩大删除范围 |

### [ADR-0073-C13] Schema 与 mixed-version 迁移按事实身份分阶段

1. **Expand**：把所有 money columns/constraints 扩展到 BIGINT；增加统一 money contract/capability、ExpenseRevision、typed linked financial event、
   mismatch acknowledgement input、projection version/dirty marker。新列/表先可双写，不改变旧投影。
2. **Backfill**：每个既有 current Expense 建立 `revision=1` baseline snapshot，明确它不是伪造的完整历史；扫描 parser/DB/Android/Web/CSV 范围、符号、
   currency 与 sum。Debt shadow rebuild 只用 parent + facts，列出依赖 mutable status 的差异。歧义/越界进入 quarantine，不自动 clamp。
3. **Dual verify**：旧/new money parser 与投影使用 golden vectors、逐账本行数/gross/refund/net/Debt remaining 对账；旧 confirmed PATCH 可以在兼容窗口由
   服务端生成 `legacy_api` revision，但不得无 revision 写入。新 refund/reversal 能力只向声明支持的客户端开放。
4. **Gate**：客户端按 capability/currency/calendar/payload revision 写入。旧后端 + 新客户端缺能力时只读/保留 intent；新 schema + 旧 binary 在任何 DDL/业务
   写前由 [[0067]] 拒绝。schema 已升级后禁止应用 rollback 到不识别 BIGINT/revision/event 的 writer。
5. **Contract**：所有 writer 均通过新 service，旧 direct-update、固定 `/100`、32-bit parser/column、status-driven Debt rebuild 和 legacy adapter 使用归零并完成
   观察窗后，才收紧 NOT NULL/CHECK、删除双读和提升 implementation status。

迁移前必须有 PostgreSQL + asset/identity 同代恢复点；迁移可重入、按主键游标 checkpoint、记录 source/target revision 和汇总 hash。不可逆 contract 只能前滚；
down migration 不得把 BIGINT 截回 INTEGER、删除 revision/event 或让旧 binary 继续写。

### [ADR-0073-C14] Repair、观测、性能与隐私同属正确性边界

repair 默认只检测和预览；执行时锁定目标 aggregate/revision，复用普通 domain invariant，写 correction/event/repair receipt，再以独立读连接重算验证。
禁止以批量 SQL 改 `amount/status/remaining/items_sum_status` 后补文档。projection repair 可重建而不改事实；事实 repair 必须有明确 actor、reason 和审计。

结构化业务审计记录 public aggregate/event ID、ledger scope、actor capability、before/after revision、command/idempotency ID、reason code、currency/calendar/fold version
和结果。普通运行日志/指标只记录事件类型、结果、延迟、queue depth、conflict/overflow/rebuild counts 和版本；不得记录金额明细、商家/备注、成员名、原图、OCR
raw text、provider payload 或凭证。敏感审计查看仍受 ledger/role 权限和导出审计约束。

热路径锁只覆盖一个 aggregate/必要关联行，不用 ledger/global mutex；DB CHECK、索引和幂等 key 是并发后盾。projection/rebuild 分批、有界内存、可暂停，使用
真实家庭容量 + 极端 fixture 测量 confirm/correction/refund p95、lock wait、projection lag 和 rebuild throughput；没有测量前不承诺虚构 SLO。若 revision/event
写放大、projection lag 或维护复杂度长期超过 [[0072]] 预算，先优化/拆分 read model，不回退事实审计和金额正确性。

## [ADR-0073-CONSEQUENCES] Consequences

- Good：同一对象为何影响余额变得可解释；现实新动作与录入更正分开；AI、计划和 proposal 不再越权成为事实。
- Good：Expense 无需全量 event sourcing 仍获得 OCC/revision/audit；Debt、退款和 reversal 保留适合 append-only 的历史与纯重建能力。
- Good：金额 carrier、上限、rounding、FX、items、splits 和 accounting date 成为一个可跨端验证的财务 envelope。
- Costs：需要 BIGINT/schema 迁移、ExpenseRevision/linked-event 模型、服务入口收口、Web/Android/CSV contract、投影 version 和恢复工具。
- Costs：confirmed 编辑、删除和退款 UX 必须要求用户区分意图；部分旧客户端进入升级/只读窗口。
- Limits：不提供复式总账、关账、银行 reconciliation 或法定不可变审计；revision 也不自动证明现实世界金额真实。
- Residual risk：授权用户仍可能确认错误事实；系统能保留来源、更正和影响，不能代替人的判断。风险由 owner 接受，并在真实错账/恢复事故后复审。

## [ADR-0073-REVERSIBILITY] Reversibility, Replacement and Retirement

增加 revision/event/projection version 的 expand 阶段可回滚应用但保留新结构；BIGINT 数据一旦超出 INTEGER 或新事件已提交，旧 writer 回滚基本不可接受，必须
前滚。Expense current aggregate + revision 可以未来迁移到 event-sourced ledger：先双写、按 revision/event 对账、证明 replay 完整，再切权威；不能直接把现有
审计行宣称为完整 event stream。typed refund/debt events 只能通过新事实纠正，不得退回负 Expense/删行。

触发 supersession：引入复式分录/多币种总账、受监管关账、跨组织结算、银行权威 reconciliation 或多 active-writer；届时需要新的 posting/period/tenant/fencing
模型。若实测证明 `MAX_ABS_MONEY_MINOR` 不足，只能通过 versioned currency contract + 全端/DB/fixture 同步迁移调整；不得单点放宽 parser。

反向验收：confirmed 字段可无 revision 改写、Debt 只靠 status 重建、负 Expense/discount 表示退款、AI 能写事实、删除被当冲正、任一端以 float/固定 `/100`
生成权威金额、或投影覆盖更新事实，任一发生即证明本架构尚未成立。

## [ADR-0073-EVIDENCE] Verification and Evidence

当前 `implementation_status=nonconformant`、`verification_status=failed`，依据是：

- `backend/app/models/expense.py` 和 `backend/app/models/debt.py` 的 principal/item/split/fact money columns 使用 SQLAlchemy `Integer`，在 PostgreSQL 对应
  32-bit INTEGER；`backend/app/schemas/_expense.py`、`_debts.py` 等入口多只有 `ge/gt`，没有统一上限。
- `backend/app/static/web/reports.js` 与多个 Jinja template 固定 `/100`，desktop chart 仍有 `Math.round`，没有消费统一 exponent/rounding contract。
- `backend/app/services/expense_service/_update.py::update_expense` 可以对 confirmed current row 原地修改 amount/currency/time 等并只更新 `row_version`；仓库没有
  `ExpenseRevision`。同文件 `reject_expense` 允许 `confirmed → rejected`，没有区分 void/correction/reversal。
- 现有 model/service 没有 typed Expense refund/chargeback/reversal aggregate；DebtAdjustment 只属于 Debt，不能替代收据退款。
- `backend/app/services/debt_service/_fold.py::derive_status` 读取 `debt.status == "voided"`，而 `_void.py` 同时写 mutable status；投影丢失后还不能只凭 DebtVoid
  facts 恢复 terminal latch。
- `receipt_item_service.py` 把人工 acknowledgement 与 derived `items_sum_status` 混在同一字符串状态；缺少独立 actor/reason/revision 输入。

成立证据至少包括：

- DB：所有 money columns 为 BIGINT + 统一 bound/sign/currency CHECK；ExpenseRevision/event FK、唯一 idempotency/reversal latch、DebtVoid 唯一约束；migration
  upgrade/中断/重跑/restore/forward-only 测试。
- TEST：边界 `±MAX`、`MAX+1`、int32 边界、sum overflow、CNY/JPY/exponent/half cases、Android/Web/CSV golden parity；stale OCC、并发 correction/refund/reversal、
  committed-but-unseen、items/splits/FX/date 原子回滚。
- REBUILD：删除所有 Debt/projection status 后只用 parent + facts 得到同一 paid/remaining/void latch；shadow Expense projection 对账 gross/refund/net、行数和 hash。
- CLIENT：用户能明确选择 correction/void/refund/recycle/privacy erase；失败页说明副作用、重试安全和数据是否仍在；旧离线 intent 不丢且 unknown contract fail closed。
- AI：provider retry/re-OCR/模型升级不能改 confirmed revision；关闭 provider 后手工路径完整。
- RUNTIME/DRILL：projection crash/backlog、migration interruption、restore 后 rebuild、privacy purge partial、旧 binary/new schema 与 long-offline client 矩阵。

在 PostgreSQL、跨端 parity、migration/rebuild 和故障演练证据都与同一 source commit/环境绑定前，本 ADR 不得标 verified。

## [ADR-0073-REFERENCES] References

- [[0061]] home currency、minor-unit exponent、ROUND_HALF_UP 与 binding revision。
- [[0066]] 家庭账务事实系统、人工确认和 adapter 边界。
- [[0067]] schema compatibility、expand/migrate/contract 与 rollback gate。
- [[0069]] 离线 intent、OCC、幂等 stable result 与 mixed-version。
- [[0070]] 带 precision 的 event-time representation、accounting date 与 calendar revision。
- [[0071]] 收据 bytes、hash、缺失状态、备份与恢复。
- [[0072]] PostgreSQL 容量、背压、任务 fault domain 与测量规则。
- [PostgreSQL — Numeric Types](https://www.postgresql.org/docs/current/datatype-numeric.html)
- [Python — Decimal rounding modes](https://docs.python.org/3/library/decimal.html#rounding-modes)
