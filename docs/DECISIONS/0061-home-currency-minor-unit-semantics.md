+++
schema_version = 2
id = "0061"
title = "Home currency 与整数 minor-unit 绑定"
summary = "兼容 *_cents 字段名，但金额语义由持久 installation currency revision 与显式 exponent 裁决"
current_scope = "home-currency identity、minor-unit exponent、rounding、跨端 capability 与 FX snapshot"
date = "2026-07-10"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "domain"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "金额、FX 与跨端协议维护者"
verification_owner = "独立财务正确性与 mixed-version reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0001"
scope = "金额单位从固定人民币分收紧为 currency-aware integer minor units"

[[relations]]
kind = "amends"
target = "0027"
scope = "home currency 从固定 CNY 收紧为持久 installation-global binding"
+++
# 0061 Home currency 与整数 minor-unit 绑定

## [ADR-0061-SCOPE] Context, Scope and Non-goals

现有字段名大量使用 `*_cents`，但 JPY/KRW exponent 为 0，且配置切换可能把同一整数解释为不同货币。当前 home currency 主要来自 env，Android/Web/CSV 仍有固定 `/100` 与 CNY fallback。本 ADR 固定金额解释边界，不授权立即启用所有币种或破坏性重命名字段。

## [ADR-0061-ASSUMPTIONS] Assumptions and Applicability

- 当前 home currency 是 installation-global；所有 ledger 的 home-only 聚合共享它。
- PostgreSQL 保存权威整数与 FX snapshot，客户端不产生权威换算。
- 长期离线客户端可能携带旧 currency contract；不能假设同步升级。

## [ADR-0061-DRIVERS] Decision Drivers

- 权威金额禁止 binary float，整数必须与币种/exponent 一起解释。
- 已有事实不能因重启改 env 被静默重解释。
- mixed-version 写入必须 fail closed，兼容字段名不能成为固定两位小数规则。

## [ADR-0061-ALTERNATIVES] Alternatives

- **A. 永久固定 CNY/除以 100**：错误处理 0 位币种，拒绝。
- **B. 立即全链重命名 `*_cents`**：迁移风险大且不解决语义绑定，拒绝。
- **C. 保留字段名，持久化 installation currency revision并下发共享 contract**：选定。
- **D. 用 Decimal major-unit 字符串建立第二真源**：扩大冲突面，拒绝。

## [ADR-0061-DECISION] Decision

### [ADR-0061-C01] 金额是带 currency context 的有界整数 minor units

`amount_cents` 等兼容字段表示其绑定币种的整数 minor units，`cents` 不再意味着固定“分”。每笔原币事实保存 currency、original minor amount 与确认时 home/FX snapshot；持久和协议 carrier 使用 [[0073]] 规定的有界 signed 64-bit 或更强精确整数。未知币种/exponent、溢出或缺 context 一律拒绝。

### [ADR-0061-C02] installation currency 是持久、版本化且不可热切换的语义身份

空安装在第一条财务事实前以数据库唯一约束原子 claim `home_currency_code + binding_revision`。env 只可初始化空库或校验已存 binding；冲突、已有库无法唯一 adoption 或配置漂移时 writer fail closed。切换已有 installation currency 需要独立迁移、备份、全量重算与对账；普通重启不得改变。

### [ADR-0061-C03] 所有 writer 消费同一 versioned currency capability

后端握手向 Android/Web/CSV 暴露 currency contract version、home currency、exponent、rounding、binding revision 与最低可写能力。只携带 home amount 的请求/outbox 必须绑定同一 revision；旧或未知 revision 返回稳定 `upgrade_required/conflict`，禁止用 User-Agent、默认 CNY、exponent=2 或字段名猜测。当前跨端 gate 未闭合前，非 CNY home currency 必须 fail closed。

### [ADR-0061-C04] rounding 与 FX snapshot 由后端冻结

major→minor 和 FX 最终取整统一 `ROUND_HALF_UP`，中间值用 Decimal。后端按原币、金额、事件日期和受信 rate生成 home snapshot；缺率保持 pending，不做 1:1，后续 rate refresh 不重算已确认事实。客户端只提交原始事实和 contract binding，不提交权威 rate。

## [ADR-0061-CONSEQUENCES] Consequences

- Good：消除 JPY/KRW 百倍错误、env 重启串账和跨端 rounding 漂移。
- Costs：需要持久 binding、capability handshake、outbox revision、跨端 formatter/parity 与迁移工具。
- Limits：`*_cents` 是长期兼容债；per-ledger currency 会改变跨账本聚合，必须 successor 决策。

## [ADR-0061-REVERSIBILITY] Reversibility, Replacement and Retirement

默认可继续 CNY，但不能恢复“所有币种两位小数”。改成 per-ledger 或迁移已有 home currency 时先 expand revision/双读、重算对账、mixed-version gate，再 contract 旧 binding；不可只改配置。

## [ADR-0061-EVIDENCE] Verification and Evidence

- CNY 12.34→1234，JPY/KRW 1000→1000；任何固定 `/100` mutation 必须使 parity test 失败。
- 写入 CNY 事实后以 JPY 配置重启必须在任何写前拒绝；两进程竞争不同初始币种只能一个 binding 胜出。
- 旧客户端、旧 outbox、未知 exponent/revision 和非 CNY 缺 capability 写入均返回稳定拒绝，不产生部分事实。
- 当前 env-only binding、CNY fallback、固定 `/100` 和无最低客户端 gate 明确违反本 ADR，因此保持 `nonconformant/failed`。

## [ADR-0061-REFERENCES] References

- [[0001]]：禁止 float 的金额基础。
- [[0027]]：后端权威 FX 与 snapshot。
- [[0069]]：离线 payload/binding 与 mixed-version。
- [[0073]]：金额宽度、更正和投影。
