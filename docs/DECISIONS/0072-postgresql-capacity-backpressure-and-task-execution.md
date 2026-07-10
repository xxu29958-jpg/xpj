+++
schema_version = 2
id = "0072"
title = "PostgreSQL 容量、背压与可恢复后台任务执行"
summary = "用 PG 任务账本和可替换 executor 隔离长任务，替代 SQLite/进程内永久假设"
current_scope = "查询/连接/资源预算、用户长任务、OCR/导入/维护背压、重启恢复和未来多实例门"
date = "2026-07-11"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "performance-capacity"
risk_level = "high"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "backend data/runtime/provider 维护者"
verification_owner = "独立性能/并发/恢复 reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "supersedes"
target = "0016"
scope = "SQLite、无后台任务框架和早期上传器规模下的性能稳定基线"

[[relations]]
kind = "supersedes"
target = "0030"
scope = "进程内 ThreadPool 作为长期任务执行模型及伪多 worker grace"

[[relations]]
kind = "refines"
target = "0066"
scope = "家庭账务事实系统的资源/故障域与 adapter 扩展缝"

[[relations]]
kind = "depends-on"
target = "0067"
scope = "任务 schema、索引、migration ownership 与 PostgreSQL 单 writer 生命周期"
+++
# 0072 PostgreSQL 容量、背压与可恢复后台任务执行

## [ADR-0072-SCOPE] Context, Scope and Non-goals

[[0016]] 把 SQLite 和“无后台任务框架”写成稳定基线，[[0030]] 又把进程内 ThreadPool 写成长期执行模型。当前系统已经
使用 PostgreSQL `background_tasks`、CSV/import/OCR/AI/scheduler/cleanup 等后台工作，但 task payload 仍只在进程内，
restart 会把 queued/running 全部 fail；singleton `enqueue_or_get_active()` 是 read-then-insert 尾部竞争；所谓 multi-worker
grace 没有原子 lease/owner，可能让一个实例误判另一个实例的任务。

本 ADR 决定家庭自托管规模下的容量边界、背压、任务事实与 executor 分层。它不引入 Kafka/Kubernetes，也不承诺当前
支持 rolling multi-instance。

## [ADR-0072-ASSUMPTIONS] Assumptions and Applicability

- 当前参考宿主为 4 logical CPU、8 GiB RAM、SSD 的 Windows 单机，一个 active backend writer 和一套 PostgreSQL。
- 家庭工作负载以短 HTTP 命令和查询为主；OCR/provider、导入、重建、备份等可慢且可异步。
- 用户可以重复点击、关闭 GUI、重启服务、断网或断电；队列不能只存在内存。
- PostgreSQL 是任务状态/claim/checkpoint 的权威；executor 是可替换 adapter，不拥有业务事实。
- 多实例在 lease/fencing、migration ownership 和 shared payload storage 成立前不受支持，配置不得只靠 grace 秒数打开。

## [ADR-0072-DRIVERS] Decision Drivers

- 单个大图片、OCR、CSV 或账本重建不能耗尽线程、DB 连接、内存、磁盘或拖垮人工记账。
- 用户必须知道任务是否排队、运行、部分完成、可取消、可重试或需 repair。
- backend restart 后不能把“行还在”冒充可恢复，也不能重复提交已完成 chunk。
- executor/host 可替换，task type、权限、幂等、checkpoint 和结果语义保持稳定。
- 性能目标必须绑定参考数据/硬件/命令，不能只写“快速稳定”。

## [ADR-0072-ALTERNATIVES] Alternatives

### [ADR-0072-ALT-A] A. 所有慢操作继续 FastAPI BackgroundTasks/ThreadPool

拒绝。payload/queue/worker owner 在内存，重启丢失，无法安全多实例或做用户可见恢复。

### [ADR-0072-ALT-B] B. 立即引入外部 broker/分布式 worker

拒绝。家庭单机运维成本、安装/恢复/供应链面显著扩大，当前吞吐无真实需求。

### [ADR-0072-ALT-C] C. PostgreSQL durable task ledger + bounded in-process executor adapter

选定。先把 task contract/claim/checkpoint 持久化；当前 executor 可保持轻量，未来真实需求出现时替换而不重写领域任务。

## [ADR-0072-DECISION] Decision

### [ADR-0072-C01] 短命请求与长任务有明确边界

普通账务命令在单一短事务内返回成功/稳定错误。预计超过 request deadline、需要多 chunk、调用慢 provider、可大量占用资源或
需要用户查看进度的操作必须进入 task ledger。HTTP 返回 task identity 和 admission outcome，不能启动不可追踪线程后返回成功。

上传文件落盘/建 pending 等最小权威动作可同步；OCR enrichment 异步失败不回滚上传。数据库 migration/restore/install 由宿主
lifecycle 管，不混入普通用户 task queue。

### [ADR-0072-C02] PostgreSQL task row 是执行协议，不只是进度 UI

每个 durable task 至少持久化：public ID、ledger/account/device principal、task type + contract version、幂等/业务 key、不可变
input reference或受限 payload、status、attempt generation、worker/lease、checkpoint、progress、result envelope、error code、
cancellation、created/started/heartbeat/completed timestamps 和 retention class。

payload 不得含 bearer、恢复 secret 或任意绝对路径；大文件使用受保护、hash 绑定的 input object。任务读写重新验证当前 principal/
ledger capability；创建者不能跨 ledger 读取旧任务。

### [ADR-0072-C03] 状态机与 claim 由数据库原子强制

```text
queued -> claimed -> running -> completed | failed | cancelled | repair-required
                    \-> retry-wait -> claimed
```

- claim 使用单条 `UPDATE ... WHERE status/retry_at/lease` + generation/fencing token 或 `FOR UPDATE SKIP LOCKED`，成功行数为 1。
- singleton 使用 partial unique business key 或 PG advisory/anchor lock，禁止 read-then-insert。
- worker 每次写 progress/result 必须带 generation；过期 worker 不能覆盖新 attempt。
- lease 到期只允许按 task type recovery policy reclaim；不使用一个全局 grace 猜所有活 worker。
- terminal result 不可重写；重试是新 attempt 或显式 successor，保留历史。

### [ADR-0072-C04] 每种 task 声明恢复和副作用策略

task registry 除 handler 外必须声明：contract version、resource class、principal/capability、singleton/business key、input validator、
chunk/checkpoint、idempotency/compensation、cancel boundary、retryable errors、max attempts、result schema、retention 和 restart policy。

允许三类：

1. **atomic**：单事务完成；失败无副作用，可安全重跑。
2. **resumable**：每 chunk 有 durable checkpoint/业务幂等键；restart 从下一未完成 chunk继续。
3. **fail-and-repair**：外部副作用无法安全自动重试；失败后进入 repair-required，向用户说明已完成边界。

没有声明/测试的 handler 不得注册。把 restart 后全部标 failed 只适用于明确 fail-and-retry task，不能伪称 resumable。

### [ADR-0072-C05] 背压先于排队和降级

- DB pool、HTTP concurrency、global/ledger/task-type/provider/image resource class 分别限额；不能共用一个无界线程池。
- admission 在持久化前检查 payload/文件大小、队列深度、磁盘保留和 per-principal 配额；超限返回稳定 429/503 + retry hint，
  不创建半任务。
- 已接纳任务按公平性调度，单个账本/provider 不能饿死人工账务或其他账本。
- OCR/AI/provider 失败可暂停/退避/关闭建议；人工创建/编辑/确认和权威读取继续可用。
- 磁盘/DB pressure 时优先拒绝新大上传/导入和非必要重建，绝不静默删除事实、outbox、图片或备份。

当前 `MAX_WORKERS=2` 可作为单机 executor 默认，不是永久架构常量；修改需与 DB pool、内存和 reference benchmark 联动。

### [ADR-0072-C06] 数据库查询和连接有支持包络

初始 release acceptance envelope（可由后继基准 ADR调整，而非静默放宽）：

| 维度 | Reference target |
| --- | --- |
| 数据 | 每 ledger 100,000 Expense；安装 10 ledger/250,000 Expense；PG 5 GiB；规范化附件 50 GiB |
| 活跃 | 20 registered devices、10 concurrent HTTP、2 concurrent heavy tasks |
| 列表/核心统计 | warm p95 ≤ 500 ms，page ≤ 100；不返回无界集合 |
| 权威短写 | 不含外部 provider 的 p95 ≤ 750 ms；事务/锁等待有 deadline |
| backend ready | 正常重启 p95 ≤ 30 s；migration/repair 明确独立预算，不假装普通启动 |
| 资源 | steady backend RSS ≤ 1.5 GiB；队列/payload/日志/临时文件均有硬上限 |

基准在固定 seed、reference machine、PostgreSQL config、冷/热条件下执行并记录 commit。目标无法满足时先 profile/索引/批处理；
需要改变支持包络必须说明用户影响和迁移，不用缓存隐藏错误查询。

### [ADR-0072-C07] 查询/投影优化不能改变权威语义

列表分页、server-side aggregate、批量 upsert、thumbnail concurrency 和短期只读 cache 保留。索引按真实 filter/order/join 设计，
EXPLAIN fixture 和统计新鲜度进入验证。缓存 key 必须含 ledger/principal/semantic revision；失效不确定时丢弃，绝不以 cache result
覆盖 PG 或用 stale projection确认写入。

N+1、全表载入、无界 JSON、在 request 内同步 OCR/大图/全量重建是 merge blocker；只有测量证明的小表例外可限时登记。

### [ADR-0072-C08] shutdown、restart 和多实例门

graceful shutdown 停止 admission、等待短事务、释放/缩短可安全 reclaim 的 lease，并留下运行 reason；不能仅 cancel futures 后让 task
行永远 running。crash/restart 根据 generation/lease/task policy恢复，不把所有 queued row 当 orphan。

多 active worker 只有在以下全部成立后由新 deployment ADR 开启：共享/受保护 payload、原子 claim+fencing、scheduler leader/lease、
task handler multi-worker tests、schema migration single owner、mixed-version兼容和 per-instance observability。当前任何“cloud grace”配置
不得打开 unsupported topology。

### [ADR-0072-C09] 取消、重试和交互语义

取消是 request，不是假定立即生效；handler 只在声明的安全边界确认 cancelled。用户界面显示 queue/running/progress/partial result/
retryable/repair-required，说明副作用和下一步。重复点击用 business/idempotency key返回同一 active/terminal task；失败重试不得覆盖
首次结果或重复业务事实。

### [ADR-0072-C10] 观测与隐私

结构化事件至少含 task public ID、type/version、ledger pseudonymous key、attempt/generation、state transition、queue/lease/wait/run duration、
resource class、result/error code 和 recovery reason。指标含 admission reject、queue depth/age、claim collision、lease expiry、retry、orphan/
repair、DB pool wait、slow query、provider saturation和磁盘压力。禁止 payload、图片、备注、token、完整路径/DSN进入日志。

## [ADR-0072-CONSEQUENCES] Consequences

Good：进程重启、重复点击、慢 provider 和未来 executor 替换有明确边界；单任务不能拖垮人工记账；性能声明可复现。Costs：task schema、
claim/lease/checkpoint、admission、基准和 UI 状态需要实现；现有 handler 要逐个分类。Limits：当前仍是单 active backend，PG 不是无限队列，
外部 broker 只有真实吞吐/隔离需求出现时再引入。Residual risk：断电可终止正在执行的外部调用，fail-and-repair task仍需人工判断。

## [ADR-0072-REVERSIBILITY] Reversibility, Replacement and Retirement

bounded in-process executor 可替换为 Windows worker、Linux service 或 broker adapter，前提是 task row/claim/fencing/result协议保持并双跑。
task contract version 采用 expand/adapter/retire；旧 payload 在 retention 窗内可解码或明确 fail/repair，不能按新 schema 猜。删除 task history 前
满足业务审计/隐私 retention。若 PG queue 锁/膨胀在 reference envelope 内无法满足 SLO，再用测量和迁移 ADR引入外部 broker。

## [ADR-0072-EVIDENCE] Verification and Evidence

- 当前失败证据：`enqueue_or_get_active()` read-then-insert；payload 仅闭包内存；restart 全 fail；multi-worker grace无 owner/fencing。
- PostgreSQL concurrency：100+并发 singleton enqueue 只产生一 active task；claim/reclaim/expired worker mutation tests。
- crash drills：commit前/后、chunk前/后、result写入前/后 kill；atomic/resumable/fail-repair分别得到声明状态且不重复事实。
- backpressure：大上传/OCR/import/provider saturation、DB pool exhaustion、磁盘低水位时人工短写保持可用或明确 fail closed。
- benchmark：固定 250k Expense/5GiB PG fixture，记录 hardware/config/commit/commands，验证 p95、RSS、pool/queue和 EXPLAIN。
- mixed executor：in-process与候选 adapter双跑相同 contract corpus，结果/claim/recovery一致后才切换。
- clean restart：queued/running 不被无条件误判；用户看见准确 recovery/repair outcome。

反向验收：两个相同 singleton 并发执行、restart 丢 payload却仍称可恢复、旧 worker 覆盖新 attempt、队列无界、OCR耗尽人工记账连接，或
缓存/投影改写 PG 事实，任一发生都证明本契约未成立。

## [ADR-0072-REFERENCES] References

- [[0066]] 家庭账务事实系统领域边界。
- [[0067]] PostgreSQL schema lifecycle 与 rollback。
- [PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [PostgreSQL SKIP LOCKED](https://www.postgresql.org/docs/current/sql-select.html)
