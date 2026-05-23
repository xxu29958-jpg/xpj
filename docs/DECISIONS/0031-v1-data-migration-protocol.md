# 0031 Use shadow database with owner-confirmed cut-over for v1.0 migration

- Status: accepted
- Date: 2026-05-23
- Decision makers: 项目维护者

## Context and Problem Statement

v1.0 主功能（[[0029]] 拆账 / [[0035]] 商品级 kind / [[0030]] background_tasks）都需要 schema 改动 + 部分表 backfill。v0.9 → v1.0 cut-over 估算 5-15 分钟，涉及 ALTER TABLE / CREATE INDEX / data backfill。

`migration_readiness_service.py` 已实现预检，但**没有"实际跑迁移、出错回滚"的代码路径**，且无 schema 版本号机制（仅 `IDENTITY_SCHEMA_VERSION = "v0.3"` frozen 字符串）。

问题：v1.0 cut-over 如何避免半成品状态、保留回滚窗口、不让 owner 在中途被迫吃下未验证的新 schema？

## Decision Drivers

- SQLite ALTER TABLE 限制大（不能 drop column / change type / add CHECK 单步）；复杂改动要 rebuild table，时点崩溃留半成品风险高
- v1.0 cut-over 是 one-shot，[[0017]] 灰度策略不适用
- owner 是唯一拥有 `/owner` 入口的用户，cut-over 由 owner 主导而非 backend 静悄悄做
- 多分钟操作期间不能让家人无差别看到"backend 503"
- 失败要能干净回到 v0.9，不依赖手工 SQL 修复

## Considered Options

- In-place ALTER directly on `ticketbox.db`, restore from backup on failure
- [Shadow Table Strategy][infoq-shadow]：在主库内建 shadow tables，CDC 同步增量，再交换
- Shadow database file（整库副本迁移）+ owner-confirmed file swap
- Side-by-side: 用户跑 v1.0 binary 指向新 DB，老库不动

## Decision Outcome

Chosen option: **Shadow database file + owner-confirmed cut-over**.

跟 [InfoQ Shadow Table Strategy][infoq-shadow] 同思想，但因为 ticketbox 是 single-file SQLite，shadow 在文件层而不是表层。流程：

1. `migration_readiness_service` 跑预检
2. Backend 复制 `ticketbox.db` → `ticketbox.v1.tmp.db`
3. 在 shadow 文件上跑 schema 改动 + backfill（作为 [[0030]] `task_type=v1_migration` 长任务跑，进度可查）
4. shadow 完成后 apply 主库期间增量（按 `created_at` / `updated_at` 拉差）
5. owner 在 `/owner/migration` 控制台 review 行数 ratio / 索引数 / 字段对齐，**点 "Confirm switch" 才进入切换**
6. Switch 时进入 1-3 s 只读窗口，apply 最后增量，原子 rename（Windows `MoveFileExW` 保证）
7. 30 天内可 rollback：将 `ticketbox.v0backup.db` rename 回主库（v1.0 期间写入数据会丢，rollback 前应手工导出）

Schema 版本用 `app_meta` 表的 `schema_version` + `schema_min_compatible` 两字段；老 binary 看到 `schema_min_compatible >= 1.0` 拒绝启动。

不选 in-place ALTER：SQLite DDL 是 implicit commit，崩在 ALTER 中途留半成品状态，restore backup 是唯一出路；这等于把"是否回滚"的决定时点推后到崩溃之后，比 shadow + owner confirm 风险高。

不选 in-DB shadow tables：[InfoQ 模型][infoq-shadow] 适合 server DB 持续接受写入的场景；本项目 single-file SQLite 文件层 shadow 更简单，整库 atomic rename 一步完成切换。

不选 side-by-side：要求用户手工指定 DB path，违反 [[0017]] "本地零运维"。

## Consequences

Good:

- shadow 阶段失败不动主库；owner 可重跑预检 / 重新生成 shadow
- owner-confirmed cut-over 让"v1.0 是否上线"由人决定，不是 backend 静悄悄做
- atomic rename 让"两个 rename 之间崩"也能自愈（启动时检测 `v0backup` 存在 + `db` 不存在 → 还原）
- 跟 [[0030]] background task 模型同框架，进度展示零增量

Bad:

- shadow 期间需要磁盘空间 ≥ DB size × 2
- 切换瞬间 1-3 s 只读窗口（家人此时上传会 503，需要 retry）
- rollback 后 v1.0 期间写入的数据丢失（除非用户手工导出）
- 跟 Alembic / Liquibase 等业界 schema migration 框架不同；自管 versioning 增加少量维护代码

## Confirmation

- atomic rename test：模拟两个 rename 之间崩，启动时自动恢复 `v0backup → db`
- schema version lock test：写完 `schema_min_compatible = "1.0"` 后老 binary 启动 → 拒绝 + 明确错误
- delta apply test：shadow 生成后主库写入 N 行；切换前 delta apply N 行；行数与主库一致
- idempotent runner test：runner 跑一半重启 → 续跑或干净失败，不留半成品
- concurrent task blocking test：有未完成 background_task 时 readiness check 红
- 30-day rollback window test：第 31 天 backup 已 purge → rollback CLI 失败 + 明确错误
- backend startup compatibility check：检测 schema_version vs binary 支持范围，不兼容时拒绝启动并指引

## More Information

- [InfoQ — Shadow Table Strategy for Data Migrations][infoq-shadow]：业界 zero-downtime migration 标准模式，本 ADR 在 file-level SQLite 上的等价实现
- [Coffee Bytes — Zero Downtime Migrations: Shadow Table Strategy Explained][coffeebytes-shadow]
- [[0030]] 长任务执行模型（迁移作为 `task_type=v1_migration` 复用同一框架）
- [[0017]] 灰度版产品边界（v1.0 cut-over 是 one-shot，不走灰度）
- [[0028]] / [[0029]] / [[0035]]：v1.0 schema 改动来源

[infoq-shadow]: https://www.infoq.com/articles/shadow-table-strategy-data-migration/
[coffeebytes-shadow]: https://coffeebytes.dev/en/databases/zero-downtime-migrations-shadow-table-strategy-explained/
