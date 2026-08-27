# 本机 PostgreSQL 运维 Runbook

小票夹后端运行在本机 PostgreSQL 上（ADR-0041）。PG-only 瘦身后 PostgreSQL 是唯一数据库，SQLite 已彻底退役。本文只覆盖源码/home-server 与测试 scratch 的 PostgreSQL 运维；不是正式 Windows 产品的备份/恢复入口。

> 决策背景见 [ADR-0041](../DECISIONS/0041-postgresql-engine-migration.md)。SQLite→PostgreSQL 的一次性迁移已于 2026-06-04 完成；迁移工具（`app.database.data_migration` + 对账 / 恢复演练脚本）已在 PG-only 瘦身中删除。本文只保留仍然适用的装库 / 备份 / 恢复步骤；历史迁移机制见 ADR-0041 与 [docs/current/CHANGELOG.md](../current/CHANGELOG.md)。

## 0. 装 PostgreSQL（home-server，一次性）

- 装 **PostgreSQL 17**（home-server 现役 `postgresql-x64-17`；CI 复用 runner 本机同一安装、经 `initdb` 起临时实例，见 `.gitea/workflows/windows-ci.yml`），默认端口 `5432`，装成 **Windows 服务并设开机自启**（EDB 安装器默认即是；`Get-Service postgresql*` 应为 `Running` + `StartType=Automatic`）。
- 建库与角色（用 `psql`，以超级用户身份）：

  ```sql
  CREATE ROLE ticketbox LOGIN PASSWORD '<强口令>';
  CREATE DATABASE ticketbox OWNER ticketbox ENCODING 'UTF8';
  ```

- 应用运行态用最小权限角色（`ticketbox`）。`backend\.env`（**不带 BOM**）的 `DATABASE_URL` 指向它：

  ```text
  DATABASE_URL=postgresql+psycopg://ticketbox:<强口令>@localhost:5432/ticketbox?require_auth=scram-sha-256
  ```

  起服后客户端用 `GET /api/auth/check` 确认 token 有效（不要用 `/api/health` 判断，见 AGENTS.md）。
- 装 PostgreSQL 客户端工具（`pg_dump` / `pg_restore`，EDB 安装器含）。备份脚本与校验服务共用一条发现链：环境变量（`PG_DUMP_PATH` / `PG_RESTORE_PATH`）→ `PATH` → `C:\Program Files\PostgreSQL\<最高版本>\bin\` 自动探测，三者都没有才报错——通常无需任何配置。
- Windows 服务启动顺序：`postgresql*` 必须先于 ticketbox 起（都 `Automatic`；起不来会在 `/api/health` 暴露）。

## 1. 备份

- 正式 Windows Manager 当前不创建完整 dataset generation；它只提供产品内 CSV 导入/已确认流水导出和只读备份记录。完整备份/恢复保持 `HOLD`，见 [WINDOWS_BACKUP_TASK.md](WINDOWS_BACKUP_TASK.md)。
- CI/source 的真实 PostgreSQL 演练运行 `python scripts/postgres_backup_drill.py --upload-root <absolute-root>`，只证明 backend archive 可在专用 scratch 库中演练；不能把它称为已出货 Windows Owner。
- PostgreSQL 工具只接收无内联口令的显式 URL 与受保护 passfile；不能从 ambient `PGPASSWORD`、
  cwd 或默认服务配置猜测凭据和目标。

## 2. 源码/测试 scratch 恢复演练

PostgreSQL 备份是 `pg_dump -Fc` 自定义格式归档（`.dump`）。本节只用于源码/测试环境把归档
恢复到独立 scratch 库，**不得**对正式安装的 `ticketbox` 库执行 `DROP/CREATE/pg_restore`。
正式 Windows 安装不得执行本节命令；当前 Manager 没有恢复入口，完整恢复继续 `HOLD`。

```powershell
cd E:\projects\xiaopiaojia
```

```sql
-- 仅在隔离的源码/测试 PostgreSQL 中创建 scratch 库：
DROP DATABASE IF EXISTS ticketbox_restore_scratch;
CREATE DATABASE ticketbox_restore_scratch OWNER ticketbox ENCODING 'UTF8';
```

```powershell
# 把归档灌进隔离 scratch 库（--no-owner 让对象归到连接角色 ticketbox）：
pg_restore --no-owner --dbname "postgresql://ticketbox:<强口令>@localhost:5432/ticketbox_restore_scratch?require_auth=scram-sha-256" `
  "<DATA_ROOT>\backups\ticketbox-YYYYMMDD-HHMMSS.dump"
```

- 对 scratch 库核对 revision、表清单、行数和关键业务不变量；完成后删除 scratch 库。
- `uploads/` 不参与这次演练，不能据此证明正式恢复后的文件/数据库一致性。
- 版本特定的回滚限制见 [ROLLBACK.md](ROLLBACK.md)。

## 3. 表属主（owner）排查 —— ALTER 迁移失败 / 启动失败

**任何向 `ticketbox` 库灌数据或建表的操作（恢复、cut-over、手工 psql）都必须以应用角色
`ticketbox` 连接执行**，不要用 `postgres` 超级用户。用超级用户建出来的对象 owner 是
`postgres`，应用角色只剩 DML 权限——平时读写一切正常，直到下一个需要 `ALTER TABLE` 的
Alembic 迁移被「必须是表的属主」拒绝，后端从此起不来。

> 实战教训（2026-06-11）：06-04 cut-over 整库由超级用户灌入，47/50 张表 owner 错位。
> 平稳运行两天后，首个 ALTER 既有表的迁移（`20260606_0001`）在启动时被拒，生产自
> 06-07 起静默停机 4 天。**真证据在 PostgreSQL 服务端日志（`data\log\`），不在应用
> `err.log`**——应用侧只看得到「启动失败」。

检查（任意角色可跑，错位对象应为 0 行）：

```sql
SELECT tablename, tableowner FROM pg_tables
WHERE schemaname = 'public' AND tableowner <> 'ticketbox';
```

修复：用超级用户跑一次 [backend/scripts/fix_table_owners.sql](../../backend/scripts/fix_table_owners.sql)
（把 database / schema / 全部表 / 序列 / 视图 owner 归位到 `ticketbox`，幂等可重跑，自带 0 行自检）：

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" `
    -U postgres -h 127.0.0.1 -d ticketbox -f backend\scripts\fix_table_owners.sql
```

预防：§2 的恢复命令已按此写——`pg_restore --no-owner` **且以 `ticketbox` 连接**，两者缺一不可
（`--no-owner` 只是「归到连接角色」，连接角色若是超级用户照样错位）。
