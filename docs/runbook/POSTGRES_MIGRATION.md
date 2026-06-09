# SQLite → 本机 PostgreSQL 迁移 / Cut-over Runbook

ADR-0041 把存储引擎从 SQLite 换到 home-server 本机 PostgreSQL。本文是**操作手册**:装库 → 迁数据 → 对账 → cut-over → 回滚。迁移机制(迁移脚本、对账、备份 dialect dispatch、恢复演练)已在 CI 的 `backend-postgres` lane 端到端验过;本文只讲在 home-server 上**真执行**的步骤。

> 决策背景见 [ADR-0041](../DECISIONS/0041-postgresql-engine-migration.md)。`row_version` 跨端 break 不在本阶段(phase ③,和引擎 cut-over 之后单独发);本阶段不碰契约。

> ⚠️ **本 cut-over 已于 2026-06-04 完成,SQLite 已彻底退役。** 一次性迁移工具(`app.database.data_migration` + 对账脚本 `migration_roundtrip_check.py`)已在 PG-only 瘦身(ADR-0041 errata)中删除,**§1–§5 仅留作历史记录、不再可执行**。仍然适用的是 §0 装库、§6 备份 / `pg_restore` 恢复——其它 runbook(ROLLBACK / WINDOWS_BACKUP_TASK / GRAY_ACCEPTANCE)指向本文的也是这两节。**§7 的「回滚回 SQLite」叙事同样已失效**(SQLite 引擎已删,app 无法再在 SQLite 上运行),与 ROLLBACK.md 的同类叙事一并待「deployment/docs PG-only」slice 重写。

## 0. 前置:装 PostgreSQL(home-server,一次性)

- 装 **PostgreSQL 16**(与 CI `postgres:16` 对齐),默认端口 `5432`,装成 **Windows 服务并设开机自启**(EDB 安装器默认即是;`Get-Service postgresql*` 应为 `Running` + `StartType=Automatic`)。
- 建库与角色(用 `psql`,以超级用户身份):

  ```sql
  CREATE ROLE ticketbox LOGIN PASSWORD '<强口令>';
  CREATE DATABASE ticketbox OWNER ticketbox ENCODING 'UTF8';
  ```

- 应用运行态用最小权限角色(`ticketbox`)。**但迁移脚本本身要超级用户**(见下一步原因)。
- 装 PostgreSQL 客户端工具(`pg_dump` / `pg_restore`,EDB 安装器含)。确认在 `PATH`,否则备份脚本认 `PG_DUMP_PATH` / `PG_RESTORE_PATH` 环境变量。

## 1. 迁移前(停机 + 备份回滚源)

```powershell
cd E:\projects\xiaopiaojia
# 1) 停后端,拿一致的 SQLite 源
powershell -ExecutionPolicy Bypass -File scripts\stop_backend.ps1
# 2) 备份当前 SQLite(这是 cut-over 后的回滚源,务必留存)
powershell -ExecutionPolicy Bypass -File backend\scripts\backup_database.ps1
```

确认 `backend\backups\ticketbox-YYYYMMDD-HHMMSS.db` 已生成。

## 2. 跑迁移脚本

迁移 = 逐表把 SQLite 灌进 PostgreSQL(保留 id、按 UTC attach 时间戳、灌后 `setval` 序列),然后**对账**。**用超级用户 DSN 跑**:脚本要 `SET session_replication_role = 'replica'` 在批量灌数据时禁 FK 触发器(处理自引用 + 加载顺序),该参数仅超级用户可设;应用运行态角色不需要这个权限。

```powershell
cd E:\projects\xiaopiaojia\backend
.\.venv\Scripts\python.exe -m app.database.data_migration `
    --source "sqlite:///data/ticketbox.db" `
    --target "postgresql+psycopg://postgres:<超级用户口令>@localhost:5432/ticketbox"
```

脚本**绝不删源**,对账任一项 `error` 即整体 FAIL、退出码非 0。

## 3. 对账 gate(必须全 PASS 才继续)

迁移脚本末尾打印逐项对账(`PASS/FAIL`),覆盖:

- **逐表行数**一致(`rowcount:<表>`)。
- **各账本 confirmed 支出合计**(`money:confirmed_by_ledger`)+ **bill_split received 笔数**(`bill_split:received_count`)。
- **抽样逐字段**(每表 head + tail 各若干行,含 timestamp / Numeric / Boolean,`sample:<表>`)。
- **序列重置**(`setval:<表>`,灌后 `nextval ≥ max(id)+1`,空表从 1 起)。

只有打印 `PASS  data-migration (N checks)`(退出码 0)才进 cut-over。**任何 FAIL:停,按报告排查,不切。** 单独复跑对账(不重灌):加 `--reconcile-only`。

## 4. Cut-over gate(ADR-0041 验收)

下面**全部**满足才翻 `DATABASE_URL`:

- [ ] `backend-postgres` CI lane 近期连续通过(双 dialect 没回归)。
- [ ] 第 3 步对账全 PASS(含序列 ≥ max(id)+1、时间戳抽样一致)。
- [ ] **pg_dump / pg_restore 恢复演练**通过(本机起一遍,见第 6 节;CI 的 recovery drill 已验机制,但 home-server 至少跑一次真备份+列档)。
- [ ] Windows 服务启动顺序验证:`postgresql*` 先于 ticketbox 起(都 `Automatic`;ticketbox 起不来会在 `/api/health` 暴露)。
- [ ] SQLite 回滚源(第 1 步备份)仍可读。

## 5. 翻 DATABASE_URL + 起服务 + 验证

改 `backend\.env`(**不带 BOM**),把 `DATABASE_URL` 指向**应用角色**(非超级用户):

```text
DATABASE_URL=postgresql+psycopg://ticketbox:<强口令>@localhost:5432/ticketbox
```

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\start_backend.ps1
powershell -ExecutionPolicy Bypass -File scripts\check_service_status.ps1 -Strict
```

客户端用 `GET /api/auth/check` 确认 token 仍有效(不要用 `/api/health` 判断,见 AGENTS.md)。Owner Console `http://127.0.0.1:8000/owner`、`/web` 各开一遍。**保留 SQLite 源 ≥ 30 天**作回滚窗口。

## 6. cut-over 后的备份

- 计划任务 `TicketboxBackup`(`scripts\maintenance_ticketbox.ps1 -Backup`)走 `pg_dump -Fc` → `<DATA_ROOT>\backups\ticketbox-*.dump`。保留天数清理按 `.dump` 后缀。配置见 [WINDOWS_BACKUP_TASK.md](WINDOWS_BACKUP_TASK.md)。
- 凭证:`pg_dump` 用 `DATABASE_URL` 内联口令,或设 `PGPASSWORD` / `%APPDATA%\postgresql\pgpass.conf`。
- **手动验一次备份可恢复**(home-server cut-over 后立刻做):

  ```powershell
  cd E:\projects\xiaopiaojia
  powershell -ExecutionPolicy Bypass -File backend\scripts\backup_database.ps1   # 产出 ticketbox-*.dump
  # 列档校验(无需起库):pg_restore --list 应列出表
  pg_restore --list "<DATA_ROOT>\backups\ticketbox-YYYYMMDD-HHMMSS.dump"
  ```

## 7. 回滚(cut-over 后发现问题)

引擎 cut-over 在保留 SQLite 源期间是**可逆**的:停服 → 把 `backend\.env` 的 `DATABASE_URL` 改回 `sqlite:///data/ticketbox.db` → 起服。详见 [ROLLBACK.md](ROLLBACK.md) 的「PostgreSQL 引擎 cut-over 回滚」。

> 注意:回滚到 SQLite 会**丢失** cut-over 之后写进 PostgreSQL 的新数据(SQLite 源停在 cut-over 时刻)。所以回滚窗口内若已有真实新账,要么接受丢失、要么反向 `pg_dump` 出来人工核对。一旦真实账本在 PostgreSQL 上长期运行,回滚需另写 ADR(ADR-0041 回收条件)。
