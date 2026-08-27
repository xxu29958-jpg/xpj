# Ticketbox Windows 数据保护当前边界

## 当前可用入口

正式 Windows Manager 的“数据保护”卡只连接两个真实消费者：

- “导入与导出”进入同源 `/web/import`，可导入 CSV，并导出当前账本的已确认流水 CSV。CSV 是业务数据副本，不是包含数据库、附件、身份和安装状态的完整备份。
- “查看备份记录”调用既有 `open_backups` 只读入口，只用于核对历史记录，不创建备份，也不执行恢复。

诊断包仍在“检查与自救”卡中，且不包含令牌、账本内容或原始日志。

## 不可用能力

当前 Manager 不暴露 `/api/backup`、`/api/backups` 或 `/api/restore` mutation，不出货或调用提权备份/恢复 helper。完整数据集备份、正式恢复以及 repair/upgrade/uninstall 生命周期仍为 `HOLD`，不能作为当前产品能力操作或宣传。

backend 中的 complete-dataset/restore 模块、历史 Windows 脚本、旧 ADR 和旧验收记录只作审计与演进输入；它们不是当前出货 Owner。单独 `pg_dump`、手工复制 uploads、`pg_restore --list`、CI green 或旧源码历史都不能冒充正式备份/恢复闭环。
