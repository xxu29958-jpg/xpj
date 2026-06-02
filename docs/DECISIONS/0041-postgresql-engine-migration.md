# 0041 存储层完整性债清偿 — 本机 PostgreSQL + row_version CAS

- Status: accepted
- Date: 2026-06-02
- Decision makers: 项目维护者

## Context and Problem Statement

本项目自始用 SQLite（单文件，home-server + Cloudflare Tunnel 自托管）。ADR-0038 把乐观并发铺到所有 mutate endpoint，CAS token 用 `updated_at`（`DateTime(timezone=True)`）。当前仍处开发/预发布期，尚未形成稳定外部安装基数；这是做一次底层存储换轨的低成本窗口。若进入长期真实账本运行后再迁移，备份、恢复、回滚、客户端兼容和人工对账成本都会显著升高。

运行至今，SQLite 在**数据完整性**上累积了一类无法在引擎内根治的债：

- **时间无类型保真**：SQLite 把 `DateTime(timezone=True)` 读回为 *naive*。`optimistic_concurrency.updated_at_predicate` 必须 `ensure_utc(v).replace(tzinfo=None)` 才能比较，否则 dialect-dependent 静默失配——OCC 正确性挂在一个 tz-strip hack 上。
- **CAS token ABA**（`expense_service/_update.py` 已记）：两次写在 ~15ms 内可产生相等 `updated_at`，stale token 误配通过。home-server 低并发下概率低、暂缓，但结构性缺陷未除。注意：这个点本身可由 SQLite 上的 `row_version` 单调列修复；它不是 PostgreSQL 独占收益。
- **约束弱**：跨列 CHECK SQLite「gets cranky」（bill_split 注释明示改由 service 层兜）；FK 要靠 per-connection `PRAGMA foreign_keys=ON`；`Numeric(18,8)` 在 SQLite 无真 NUMERIC（存 TEXT/REAL）；TEXT affinity 宽松类型——DB 层不挡脏数据，全靠应用层自律。

问题不是“为了 row_version 必须换 PostgreSQL”。问题是：既然开发期已经要做一次跨端 OCC token 破坏性变更，要不要顺手把长期会反复牵制 schema / 备份 / 约束 / 时间语义的 SQLite 引擎债一起还掉。PostgreSQL 把「时间是 timestamptz、外键强制、CHECK 可跨列、类型严格」作为默认能力，让 DB 层成为数据正确（§0 #1）的第一道防线。

## Decision Drivers

- §0 #1 数据正确优先：DB 层强制 > 应用层自律。
- 开发期窗口：现在切换存储引擎比稳定发布后低风险；若等真实历史继续增长，迁移风险只会变大。
- §6 服务端是业务真源；schema 迁移需可执行回滚 + 恢复演练。
- §7 并发写版本号保护：`row_version` 单调列根治 ABA（替 `updated_at`-as-CAS）。
- §9 依赖治理：引入 `psycopg`（成熟、活跃、宽松许可）。
- 自托管边界：Postgres 必须能本机随 backend 起，不引入云依赖。

## Considered Options

- **A. 维持 SQLite 现状**——继续 tz-strip hack、service 层兜 invariant、PRAGMA-FK、ABA 暂缓。
- **B. 留 SQLite 但加固**——SQLite 3.37 STRICT 表 + `row_version` 列 + 补能加的 CHECK。它能根治 ABA，是最低风险 fallback；但 timestamptz 仍无（naive 问题不除）、跨列 CHECK/类型约束能力仍弱、FK 仍 pragma-gated，DB 层仍不是完整第一道防线。
- **C. 迁本机 PostgreSQL（本 ADR 选）**——strict 类型 + timestamptz + 强制 FK/CHECK；把 `row_version` 折进同一轮 schema/contract 破坏性变更，避免先做 row_version-only、再做 engine migration 的二次跨端 churn。
- **D. 托管/远程 Postgres（RDS/Azure 等）**——否：破自托管边界，且未选并发/扩展驱动。

## Decision Outcome

Chosen: **C — 迁本机 PostgreSQL**。本 ADR 的目的不是“换引擎”，而是在开发期把存储层完整性债还掉：时间语义、FK/CHECK/类型约束、备份恢复和 OCC token 一次性收口。PostgreSQL 是实现这个目标的本机自托管强约束 RDBMS；驱动不是并发扩展，也不是上云。

- **不是因为 SQLite 不能做 row_version**：`row_version` 在 SQLite 上可落地，也会作为本 ADR 的 fallback 方案保留。选择 PostgreSQL 是因为开发期可以承受一次底层换轨，而不是把长期引擎债推到稳定发布后。
- **本机部署**：Postgres 作 home-server Windows 上的本地服务（与 backend 同机，localhost 连接）；不经 Tunnel 暴露、不上云。`DATABASE_URL` 由 `sqlite:///…` 改 `postgresql+psycopg://…@localhost/…`，是唯一切换点。
- **dialect 收敛**：ORM/Alembic 已抽象多数差异。SQLite-only 面 dialect-conditional 或退场——`migrate_sqlite_schema` 系列（`INSERT OR IGNORE` / `PRAGMA` / 启动期 raw DDL）在 Postgres 下 **no-op**，Postgres 走 **Alembic 唯一权威**；`check_same_thread`/`StaticPool`/PRAGMA-FK hook 仅 SQLite；partial index 补 `postgresql_where`；月份格式 CHECK 保留 `length(month)=7`（SQLite 3.45 无 `char_length` 函数，对 varchar 列 `length()` 在两 dialect 等价、已是 dialect-safe；起草时写的「换 `char_length`」会反而搞挂 dev SQLite，phase-1 实测后更正）。
- **row_version**：各 OCC 表加单调 `row_version` int，CAS 由 `UPDATE … SET row_version=row_version+1 WHERE id AND row_version=:expected` 取代 `updated_at` 比较（`updated_at` 保留作展示/排序）。API token 字段 `expected_updated_at` → `expected_row_version: int`：跨端契约破坏性变更，沿用 ADR-0038「不兼容旧客户端、同 release 发」前提。
- **数据迁移**（最高风险）：一次性脚本 SQLite→Postgres，迁后**对账**（逐表行数 + 关键财务汇总 reconcile + 抽样逐字段）；迁移期保留 SQLite 为回滚源，对账通过 + 恢复演练完成才退役；复用 ADR-0031 backup snapshot + rollback 窗口。
- **测试**：CI 增 Postgres lane 跑全套（catch dialect 漂移）；开发期可短暂双 dialect，但生产 cut-over 前必须确定一个主路径。若继续保留 in-memory SQLite 作为快速测试，只允许覆盖纯 service/unit 层，migration/OCC/备份恢复/约束测试必须在 Postgres 过。
- **备份**：`backup_service` / `.ps1` 由 sqlite file-copy 抽象成 dialect dispatch（Postgres 走 `pg_dump`/`pg_restore`）；runbook 重写。

A 否：继续接受已知结构债。B 不作为首选：它能修 ABA，但会留下时间语义、强类型、跨列约束和 FK enforcement 的引擎债；若现在已经要做跨端 token 破坏性变更，开发期一次性完成存储层升级更划算。D 否：无对应驱动、破自托管边界。

## Consequences

Good：
- 时间/FK/CHECK/类型由 DB 强制——`updated_at_predicate` 的 tz-strip hack 退场，OCC 不再挂在 naive-datetime 上。
- `row_version` 根治 ABA（闭合 `_update.py` 记的 residual risk）。
- 跨列 CHECK / 强 FK 把「service 层兜的 invariant」下沉 DB，少一层信任假设。
- legacy `_validate_*`（family-role / unique-scope）应用层完整性修复被 Postgres 强制 FK/UNIQUE/CHECK 取代——正是本 ADR「DB 当第一道防线」的兑现。

Bad / 成本：
- **一次性数据迁移高风险**（真实账目历史）——靠对账 + 回滚源 + 恢复演练兜底，不演练不切。两枚必须脚本显式处理的地雷：① naive datetime → `timestamptz` 须按 **UTC** attach（错按本地时区则全表时间偏移、月边界统计错配，本项目已两栽此类）；② 保留原 `id` 灌数据后 Postgres SERIAL/IDENTITY 序列不前进，每表须 `setval` 到 `max(id)`，否则首条新建撞 PK。
- 部署多一组件：home-server 要装/起/备份 Postgres（Windows 服务 + 开机起 + pg_dump 任务）。
- 跨端 OCC token 破坏性变更（5 schema + 路由 + /web hidden 字段 + Android DTO + mutate-token 审计）同 release 改齐。
- `migrate_sqlite_schema` 退居 SQLite-only；Postgres 全靠 Alembic，baseline/replay 流程在 Postgres 重验。
- 双 dialect 维护期（dev SQLite / prod Postgres）有漂移风险，靠 CI Postgres lane 兜。

回收条件：若数据迁移对账/恢复演练反复失败、Postgres lane 长期不稳定、或本机 Postgres 运维成本超出自托管承受，回退 B（SQLite STRICT + row_version），保留本 ADR 的 row_version 设计成果。回退必须发生在 cut-over 前；一旦真实账本在 Postgres 上进入长期运行，回退需另写 ADR。

## Confirmation

- 迁移脚本对账测试：迁后逐表行数一致 + 关键财务汇总（各账本 confirmed 支出合计、bill_split received 笔数）reconcile + 抽样行逐字段比对。
- 序列重置 gate：灌数据后每表 `setval(pg_get_serial_sequence('t','id'), max(id))`，对账确认各表序列 ≥ `max(id)+1`（不补 cut-over 后首条新建撞 PK）。
- 时间戳迁移 gate：naive datetime 按 UTC attach 进 `timestamptz`；抽样比对若干已知行（某 expense 的 `expense_time`/`confirmed_at`）迁移前后值一致。
- 导出前置：确认源 SQLite 的 legacy backfill（`tenant_id`/`public_id`/FX）已全应用——Postgres 不再跑 `migrate_sqlite_schema` 的数据修复。
- OCC read/read/write/write 测试在 **Postgres** 上过：两会话同 `row_version`，第一个 commit、第二个 `UPDATE … WHERE row_version=expected` rowcount=0 → 409（证明 DB predicate，非 Python 比较）。
- dialect 收敛审计：`release_audit` 加检查——无 SQLite-only raw SQL 漏到 Postgres 路径；partial index 都有 `postgresql_where`。
- 恢复演练：`pg_dump` → 新库 `pg_restore` → 应用起得来 + `/api/auth/check` 通过（§11：没演练等于没备份）。
- mutate-token 审计继续 0 known gaps；token 切 row_version 后契约测试三端对齐。
- cut-over gate：Postgres lane 连续通过、迁移对账（含序列 ≥ max(id)+1、时间戳抽样）通过、pg_dump/pg_restore 演练通过、Windows 服务启动顺序验证通过、SQLite 回滚源仍可读。

## More Information

- [[0038]] Multi-Surface Sync——本 ADR 把其 `updated_at`-as-CAS 升级为 `row_version`；ADR-0038 的 409/contract 形态不变。
- [[0031]] v1.0 Data Migration Protocol——复用 backup snapshot + rollback 窗口。
- [[0030]] Long Task Execution Model——迁移脚本若长跑复用其执行模型。
- `expense_service/_update.py` residual-ABA docstring 落地后更新指向本 ADR。
- 实现按 phase 切多 PR：① dialect-proofing（留 SQLite 跑、双 dialect CI）→ ② 本机 Postgres + 迁移脚本 + 对账/演练 → ③ cut-over。gated on PR-C #208 merged。
- ENGINEERING_RULES §0 / §6 / §7 / §9 / §11 / §14。
