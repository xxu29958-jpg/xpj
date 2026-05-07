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

边界：

- 不提交 `backend/backups/`。
- 不把真实 Token 写进备份文档、日志或 Git。
- 备份只复制 SQLite 文件，不上传云端。
- 默认只保留最近 30 天的 `ticketbox-*.db` 备份。
- 清理图片不影响 confirmed 账本数据。
