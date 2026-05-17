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
backend/backups/
```

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

## 从备份恢复

恢复前请先停止后端，避免运行中的 SQLite 文件被覆盖：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_backend.ps1
```

恢复指定备份：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\restore_ticketbox_db.ps1 -BackupPath "backend\backups\ticketbox-20260508-033000.db"
```

恢复脚本会：

1. 校验备份文件必须是 `.db`。
2. 执行 SQLite `PRAGMA integrity_check`。
3. 如果当前数据库存在，先用 SQLite Online Backup API 创建 `ticketbox-before-restore-*.db`。
4. 再覆盖 `backend/data/ticketbox.db`。
5. 覆盖后再次校验数据库。

如果确认要在后端运行时强制恢复，可以传入 `-ForceWhileRunning`，但日常不建议这样做。

边界：

- 不提交 `backend/backups/`。
- 不把真实 Token 写进备份文档、日志或 Git。
- 备份只在本机用 SQLite Online Backup API 生成一致快照，不上传云端。
- 默认只保留最近 30 天的 `ticketbox-*.db` 备份。
- 恢复脚本只恢复 SQLite 数据库，不删除 uploads 图片。
- 清理图片不影响 confirmed 账本数据。
