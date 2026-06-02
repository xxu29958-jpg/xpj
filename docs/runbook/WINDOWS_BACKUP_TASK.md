# 小票夹 Windows 自动备份任务

小票夹的主数据源是 Windows 后端 SQLite 数据库：

```text
backend/data/ticketbox.db
```

`scripts\install_windows_tasks.ps1` 默认会创建每日备份任务：

```text
TicketboxBackup
```

默认执行时间为每天 `03:30`，实际运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\maintenance_ticketbox.ps1 -Backup -BackupRetentionDays 30
```

备份文件写入：

```text
<DATA_ROOT>/backups/
```

`DATA_ROOT` 跟随部署形态(`backend/app/services/backup_service.py:_BACKUP_DIR = DATA_ROOT / "backups"`):

- 源码运行(`uvicorn app.main:app` from `backend/`):`DATA_ROOT = backend/`,实际路径 `backend/backups/`。
- 冻结 EXE 部署:启动器把 `TICKETBOX_DATA_DIR` 指到 `ticketbox-data\`,实际路径 `ticketbox-data\backups\`。
- 任何运行形态下,实际路径都可以用 `Owner Console`「备份」页面看到。

调整备份时间：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -BackupTime "02:10"
```

调整自动保留天数：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -BackupRetentionDays 14
```

手动清理超过保留天数的旧备份：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\maintenance_ticketbox.ps1 -PruneBackups -BackupRetentionDays 30
```

如果只想手动备份但暂时不清理旧备份：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\maintenance_ticketbox.ps1 -Backup -SkipBackupPrune
```

只安装后端和 Tunnel，不创建自动备份：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -SkipBackup
```

卸载计划任务时，默认会一起移除 `TicketboxBackup`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall_windows_tasks.ps1
```

如果要保留备份任务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall_windows_tasks.ps1 -SkipBackup
```

## PostgreSQL（ADR-0041 cut-over 后）

cut-over 到本机 PostgreSQL 后（执行手册 [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md)），**同一个** `TicketboxBackup` 任务无需改动：`maintenance_ticketbox.ps1 -Backup` 按 `DATABASE_URL` 的 dialect 自动切换——

- **PostgreSQL**：`pg_dump -Fc` → `<DATA_ROOT>\backups\ticketbox-*.dump`（自定义格式归档），并用 `pg_restore --list` 校验归档可读；保留天数清理按 `.dump` 后缀。备份逻辑委托给 [backend/scripts/backup_database.ps1](../../backend/scripts/backup_database.ps1)（dialect 单一真相源）。
- **SQLite**：仍是 SQLite Online Backup 快照 `.db`。

凭证与二进制：

- `pg_dump` 需在 `PATH`，否则设 `PG_DUMP_PATH`（计划任务所属服务账户的环境）。
- 口令走 `DATABASE_URL` 内联，或 `PGPASSWORD` / `%APPDATA%\postgresql\pgpass.conf`（任务以哪个账户跑就配哪个账户的 `pgpass`）。

PostgreSQL 恢复**不**走下方的 `restore_ticketbox_db.ps1`（它只认 SQLite `.db`）；用 `pg_restore`，见 [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md)。

## 从备份恢复

恢复前请先停止后端，避免运行中的 SQLite 文件被覆盖：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_backend.ps1
```

恢复指定备份：

```powershell
# 源码运行(DATA_ROOT = backend):
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\restore_ticketbox_db.ps1 -BackupPath "backend\backups\ticketbox-20260508-033000.db"
# 冻结 EXE 部署(TICKETBOX_DATA_DIR=ticketbox-data\):
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\restore_ticketbox_db.ps1 -BackupPath "ticketbox-data\backups\ticketbox-20260508-033000.db"
```

恢复脚本会：

1. 校验备份文件必须是 `.db`。
2. 执行 SQLite `PRAGMA integrity_check`。
3. 如果当前数据库存在，先用 SQLite Online Backup API 创建 `ticketbox-before-restore-*.db`。
4. 再覆盖 `backend/data/ticketbox.db`。
5. 覆盖后再次校验数据库。

如果确认要在后端运行时强制恢复，可以传入 `-ForceWhileRunning`，但日常不建议这样做。

边界：

- 不提交 `backend/backups/` 或 `ticketbox-data/backups/`(`.gitignore` 已覆盖)。
- 不把真实 Token 写进备份文档、日志或 Git。
- 备份只在本机用 SQLite Online Backup API 生成一致快照，不上传云端。
- 默认只保留最近 30 天的备份（SQLite `ticketbox-*.db` / PostgreSQL `ticketbox-*.dump`，按当前 dialect）。
- 恢复脚本只恢复 SQLite 数据库，不删除 uploads 图片。
- 清理图片不影响 confirmed 账本数据。
