# 本机 PostgreSQL 运维 Runbook

小票夹后端运行在 home-server 本机 PostgreSQL 上（ADR-0041）。PG-only 瘦身后 PostgreSQL 是唯一数据库，SQLite 已彻底退役。本文是 home-server 上的 PostgreSQL **运维手册**：装库、备份、恢复。

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
  DATABASE_URL=postgresql+psycopg://ticketbox:<强口令>@localhost:5432/ticketbox
  ```

  起服后客户端用 `GET /api/auth/check` 确认 token 有效（不要用 `/api/health` 判断，见 AGENTS.md）。
- 装 PostgreSQL 客户端工具（`pg_dump` / `pg_restore`，EDB 安装器含）。备份脚本与校验服务共用一条发现链：环境变量（`PG_DUMP_PATH` / `PG_RESTORE_PATH`）→ `PATH` → `C:\Program Files\PostgreSQL\<最高版本>\bin\` 自动探测，三者都没有才报错——通常无需任何配置。
- Windows 服务启动顺序：`postgresql*` 必须先于 ticketbox 起（都 `Automatic`；起不来会在 `/api/health` 暴露）。

## 1. 备份

- 计划任务 `TicketboxBackup`（`scripts\maintenance_ticketbox.ps1 -Backup`）走 `pg_dump -Fc` → `<DATA_ROOT>\backups\ticketbox-*.dump`。保留天数清理按 `.dump` 后缀。配置见 [WINDOWS_BACKUP_TASK.md](WINDOWS_BACKUP_TASK.md)。
- 凭证：`pg_dump` 用 `DATABASE_URL` 内联口令，或设 `PGPASSWORD` / `%APPDATA%\postgresql\pgpass.conf`。
- **手动备份 + 列档校验**（建议每次大改前各做一次）：

  ```powershell
  cd E:\projects\xiaopiaojia
  powershell -ExecutionPolicy Bypass -File backend\scripts\backup_database.ps1   # 产出 ticketbox-*.dump
  # 列档校验(无需起库)：pg_restore --list 应列出表
  pg_restore --list "<DATA_ROOT>\backups\ticketbox-YYYYMMDD-HHMMSS.dump"
  ```

## 2. 从备份恢复

PostgreSQL 备份是 `pg_dump -Fc` 自定义格式归档（`.dump`），用 `pg_restore` 恢复。**先停后端**；生产恢复重建 `ticketbox` 库，演练 / 核对时恢复到一个 scratch 库（不要碰生产）：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\stop_backend.ps1
```

```sql
-- 用超级用户 psql 重建目标库（确保没有活动连接）：
DROP DATABASE IF EXISTS ticketbox;
CREATE DATABASE ticketbox OWNER ticketbox ENCODING 'UTF8';
```

```powershell
# 把归档灌进新建的空库（--no-owner 让对象归到连接角色 ticketbox）：
pg_restore --no-owner --dbname "postgresql://ticketbox:<强口令>@localhost:5432/ticketbox" `
  "<DATA_ROOT>\backups\ticketbox-YYYYMMDD-HHMMSS.dump"
powershell -ExecutionPolicy Bypass -File scripts\start_backend.ps1
powershell -ExecutionPolicy Bypass -File scripts\check_service_status.ps1 -Strict
```

- `uploads/` 目录不随库恢复改动——图片路径以数据库 `expenses.image_path` 为权威，恢复库后图片自然对齐。
- 起库后用 `GET /api/auth/check` 确认 token 仍有效。版本特定的回滚注意见 [ROLLBACK.md](ROLLBACK.md)。

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
