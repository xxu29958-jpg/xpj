+++
schema_version = 2
id = "0070"
title = "账务时间、归属日期与账本 calendar binding"
summary = "分离事件瞬时、账务归属日期和系统审计时间，禁止请求时区重切历史月份"
current_scope = "Expense/导入/OCR/通知的时间输入、ledger timezone revision、统计归属、DST 与 mixed-version"
date = "2026-07-11"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "domain"
risk_level = "high"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "financial domain、API、migration 与客户端维护者"
verification_owner = "独立财务语义/migration reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "supersedes"
target = "0002"
scope = "消费时间相对创建时间的当前统计规则；历史分离原则继续保留"

[[relations]]
kind = "refines"
target = "0061"
scope = "沿用 home-currency 的持久语义与 mixed-version 门方法，但 calendar 维持 ledger-scoped、currency 维持 installation-scoped"

[[relations]]
kind = "refines"
target = "0066"
scope = "家庭账务事实中的事件时间、归属日期和系统时间"

[[relations]]
kind = "depends-on"
target = "0067"
scope = "新增持久 calendar binding、backfill 与不可逆 contract 的 schema lifecycle"
+++
# 0070 账务时间、归属日期与账本 calendar binding

## [ADR-0070-SCOPE] Context, Scope and Non-goals

[[0002]] 正确区分了 `expense_time` 与 `created_at`，但只用 `COALESCE(expense_time, confirmed_at)` 不能定义家庭
账务日历。当前不同入口对 naive datetime 有“按 UTC”与“按配置本地时区”两种解释，统计/报表还接受请求 timezone，
修改 env 或 query 就可能把已确认交易切到另一个月份。设备错钟、DST gap/fold、账本换时区和长期离线客户端也没有
稳定协议。

本 ADR 决定发生瞬时、账务归属日期、展示时区和系统审计时间。它不实现完整会计期间/关账，也不为每个家庭建立
企业级日历服务。

## [ADR-0070-ASSUMPTIONS] Assumptions and Applicability

- 一个账本在任一 revision 下只有一个 IANA accounting timezone；成员设备可处于不同时区。
- 绝大多数消费可表达为带 offset 的瞬时；无法确定时刻的历史资料必须显式标精度/歧义，不能伪造 UTC。
- 家庭用户可以纠正消费时间，但纠正是显式财务修订，必须同时更新归属日期和审计。
- PostgreSQL `timestamptz` 保存瞬时；本地日期和 zone/revision 需要独立字段，不能靠 DB/session timezone 隐含。
- 日历绑定改变较少，允许受控迁移；查询和 UI timezone 可以改变显示，不能改变余额归属。

## [ADR-0070-DRIVERS] Decision Drivers

- 月度预算、报表、重复检测、FX rate date 和债务/分账必须对同一交易得到相同归属日期。
- 改服务器 env、浏览器 query 或手机时区不能重写历史月份。
- DST gap/fold、offset/zone 不一致、naive 输入和设备错钟必须有可证伪行为，而非静默 fallback。
- 新旧客户端、导入、OCR 和通知入口必须共享同一 canonicalization service。
- 迁移要能识别歧义行，允许暂停/人工校正，不能批量猜测后宣称成功。

## [ADR-0070-ALTERNATIVES] Alternatives

### [ADR-0070-ALT-A] A. 每次查询传 timezone 动态切月

拒绝。展示方便但同一事实的月份随调用方变化，预算、报表和客户端缓存无法对账。

### [ADR-0070-ALT-B] B. 全部按 UTC 日期归属

拒绝。简单但会把本地午夜附近的家庭消费归入错误日期/月，且无法解释用户日历。

### [ADR-0070-ALT-C] C. 瞬时 + 冻结 accounting date + ledger calendar revision

选定。瞬时保留排序/时差能力，归属日期稳定预算/报表，revision 让日历改变可迁移、可审计。

## [ADR-0070-DECISION] Decision

### [ADR-0070-C01] 四种时间语义必须分开

| 语义 | 表达 | 写入者/用途 |
| --- | --- | --- |
| event instant | offset-aware UTC instant + 可选 source zone/precision | 用户/受控入口提供；排序、FX date 候选、证据 |
| accounting date | `YYYY-MM-DD` + ledger calendar revision | 后端在确认/显式修订时冻结；预算、报表、月度归属 |
| display time | viewer 选择的 IANA zone | 客户端/模板只负责展示，不写回归属 |
| system/audit time | 服务端 UTC `created/updated/confirmed/revoked/received` | 服务端/数据库；安全 TTL、审计、OCC 辅助 |

`uploaded_at/received_at` 不能替代消费时间；`created_at` 不能进入账务聚合；展示日期不能反写 accounting date。

### [ADR-0070-C02] ledger calendar binding 是持久语义，不是 env 调优

每个 Ledger 持久化 `accounting_timezone`（IANA zone）和单调 `calendar_revision`。安装默认值只在创建账本时生成，
之后 env/request 不得重解释既有事实。Expense 在确认时保存 `accounting_date` 和使用的 revision/zone snapshot。

改变账本 timezone 只影响新确认/新修订事实，除非 owner 启动显式历史迁移。多账本可以不同 zone；未来云端/多机读取同一
持久 binding，不依赖宿主本地时区。

### [ADR-0070-C03] 新写入只接受可判定时间

- 稳定 API 的 event instant 必须是 RFC 3339/ISO-8601 且含 offset；naive datetime 默认拒绝。
- zone+local datetime 若用于录入，服务端校验 IANA zone。DST gap 拒绝并要求用户选择；fold 必须带 offset/fold 选择。
- offset 与声明 zone 在该 instant 不一致时拒绝，不能任选其一。
- 只有明确 legacy/versioned adapter 可以解释 naive 值，并必须记录采用的 zone/revision与迁移来源；适配器有退役门。
- 仅知道日期而不知道时刻的导入不得伪造中午/UTC；使用明确 date-only/precision 状态，当前 schema 未支持时 fail closed 或
  进入人工 review。

### [ADR-0070-C04] accounting date 由后端统一冻结

pending suggestion 可以携带 event instant/date candidate，但不形成账务归属。人工确认或明确业务命令在同一事务中：

1. 校验 event time/precision；
2. 读取并锁定 ledger calendar revision；
3. 计算 accounting date；
4. 写 Expense/current correction、revision snapshot 和审计；
5. 再让 budget/report/projection 消费该 date。

所有统计、预算、报表、重复检测、规则批处理和 Android sync 使用持久 accounting date；query timezone 仅改变展示。

### [ADR-0070-C05] 时间更正是显式财务修订

授权用户可以修正 event time。已确认 Expense 的修订必须 OCC 成功，并在同事务重新计算 accounting date、记录旧/新 instant、
旧/新 date、actor/reason/revision，随后使相关投影失效/重建。禁止只 PATCH `expense_time` 留下旧月份投影，或后台 OCR/设备同步
在无用户命令时改变已确认时间。

是否未来改成 append-only correction fact 由财务事实 ADR 决定；在此之前不能把当前原地修订描述为 append-only。

### [ADR-0070-C06] 设备时间不是安全、顺序或重放权威

token/pairing/UploadLink expiry、created/confirmed/audit、server row_version、idempotency retention、outbox 服务端接收顺序和
安装 timeout 由服务端 UTC/单调时钟裁决。客户端 wall clock 只辅助 UX/本地 age 显示；回拨/快进不能复活凭证、绕过 age cap、
覆盖更新事实或改变 ledger revision。

离线 intent 保存用户选择的 event time/zone/precision 以及 payload/calendar contract revision；重连时发现 revision 改变必须
显式 rebase/review，不得按新 zone 静默重算旧 payload。

### [ADR-0070-C07] calendar 迁移遵循 expand → backfill → gate → contract

1. Expand：新增 ledger binding、Expense accounting date/revision/precision nullable 字段和双读能力，不改变旧聚合。
2. Backfill：按已记录 offset/source zone/现行兼容规则计算；逐批游标、行数、月份汇总和 ambiguity 清单可重入。
3. Gate：旧客户端/旧 outbox 不能再产生无 contract 的时间；unknown revision 返回 `upgrade_required`/review。
4. Contract：只有 ambiguity=0、全量财务汇总对账、N/N-1 矩阵和恢复点通过后，聚合切到 accounting date 并收紧 NOT NULL。

无法证明 source zone 的历史行必须保留“legacy assumed zone”证据或人工修订，不得在 backfill 中伪装精确。

### [ADR-0070-C08] mixed-version 行为

- 新后端 + 旧客户端：在兼容窗口只接受可无歧义转换的 offset-aware payload；否则要求升级，保留本地 intent。
- 旧后端 + 新客户端：能力缺失时客户端只读/阻止新时间语义写入，不丢 outbox。
- 新 schema + 旧 binary：[[0067]] compatibility gate 在任何业务/DDL 写之前拒绝。
- 长离线：比较 payload、calendar 和 ledger binding revision；账本时区改变时进入用户 review。
- Web 不作为持久离线 writer；浏览器 display zone 不能成为服务器 accounting zone。

### [ADR-0070-C09] 性能与可观测性

Expense 以 `(ledger_id, accounting_date, status)` 等实际查询形态建立索引；月度统计不得在每行动态 `AT TIME ZONE` 扫描重切。
迁移记录 scanned/migrated/ambiguous/failed/remaining、每月前后计数和金额总和。运行信号记录 invalid offset/zone、revision conflict、
legacy adapter use 和 clock skew bucket，但禁止记录 token、完整备注或原图。SLO/索引依据实际容量压测，不预设企业规模。

## [ADR-0070-CONSEQUENCES] Consequences

Good：同一账务事实跨 Android/Web/报表/预算得到稳定月份；改 env/query/设备时区不再重写历史；DST 和长期离线可显式处理。
Costs：需要 ledger/Expense schema、backfill、索引、能力握手和客户端 payload 变更；历史数据可能出现需人工确认的 ambiguity。
Limits：不提供企业关账/会计期间；当前代码在落地前明确 nonconformant。Residual risk：用户可以有意选择错误时间，系统只能保留
actor/reason/provenance，不能判断现实世界真伪。

## [ADR-0070-REVERSIBILITY] Reversibility, Replacement and Retirement

Expand 阶段可回退应用而保留新列；切换聚合前可双算比较。Contract 后若新事实只保存 accounting date/revision 而旧 binary 不认识，
属于 forward-only；不得 down migration 丢字段或让旧应用继续写。改变 ledger timezone 的历史重算是高代价、可能改变预算/报表的
显式迁移，执行前需要备份/预览/owner确认并保存 old mapping；不能通过改 env 撤销。

若未来引入完整会计期间/关账或多 jurisdiction，本 ADR 由更强 calendar policy supersede；瞬时/归属/系统时间分离仍保留。

## [ADR-0070-EVIDENCE] Verification and Evidence

- 当前失败证据：`time_service.py` 对 naive/非法 zone 存在 UTC fallback；CSV/OCR/手工入口解释不一；budget/report 接受请求 timezone；
  Ledger 无持久 calendar binding，Expense 无 accounting date/revision。
- DB：IANA zone/revision/binding 约束、Expense snapshot/foreign relation、必要索引；旧 writer 在 contract 后稳定失败。
- TEST：DST gap/fold、闰日、月/年边界、offset-zone mismatch、设备快/慢/回拨、time correction OCC、跨账本 zone。
- MIGRATION：中断/重跑、ambiguity、按月行数和 minor-unit 汇总、N/N-1 binary/schema、restore/forward-fix。
- CLIENT：Android/Web 同一 fixture 得到同 accounting date；display zone 改变只变文案；旧 outbox revision conflict 不丢 intent。
- RUNTIME：legacy adapter 使用降至零且观察窗完成后才 contract。

反向验收：改变 env/query/device zone 会改变已确认交易月份、naive 输入被静默接受、DST fold 得到随机结果、旧 outbox 按新 calendar
重算，或时间更正没有同步更新归属/审计，任一发生都证明本契约未成立。

## [ADR-0070-REFERENCES] References

- [[0066]] 家庭账务事实系统边界。
- [[0067]] PostgreSQL schema lifecycle 与 rollback。
- [PostgreSQL date/time types](https://www.postgresql.org/docs/current/datatype-datetime.html)
- [IANA Time Zone Database](https://www.iana.org/time-zones)
