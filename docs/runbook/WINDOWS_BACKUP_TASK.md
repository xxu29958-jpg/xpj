# Ticketbox Windows 完整数据集备份与恢复

## 当前出货边界

正式 Windows 安装没有 `TicketboxBackup` 计划任务，也不再出货 DB-only
`backup_database.ps1`。唯一用户入口是桌面管理器：

- “立即备份”经短时提权 helper 调用已安装的
  `installer\windows_dataset_backup.ps1`。
- “恢复”必须由用户明确选择一个 `ticketbox-backup-<UUID>` generation，再经短时提权 helper
  调用 `installer\windows_dataset_restore.ps1`。
- 源码模式没有正式安装 backup/restore owner；源码历史只用于演进和测试，不构成正式运行记录。

## 完整备份 generation

备份写入 `<DataRoot>\backups\ticketbox-backup-<UUID>\`，并且只有整个目录完成校验后才原子
发布。generation 包含：

- 严格、不可变的 `manifest.json`，绑定 Dataset Authority、restore epoch、schema revision、
  writer fence、release 和每个 artifact 的长度/hash；
- PostgreSQL custom-format archive；
- 数据库仍然引用的全部原始附件。

备份 owner 在第一笔数据读取前验证 installed identity、Generation CURRENT 和服务合同，停止 backend
writer，确认 PostgreSQL 没有其他 client writer，再调用 frozen backend 的 complete-dataset helper。
任一数据库、附件、manifest 或 publication 失败只留下失败，不发布半个 generation。

## 恢复

恢复 owner 先把明确选择的 generation 校验为同一 Dataset Authority，再在任何停服或覆盖前持久化
恢复请求。它将数据库恢复到隔离候选集群、重建 originals、重读 live database identity，随后同卷
提升候选。最终 CURRENT 仍只由 H1 Generation Owner 发布；restore、journal、receipt 和 historical
reader 都没有第二份 current/publication 权限。

崩溃重试从 durable request、candidate evidence、Dataset Authority 和 CURRENT 重新分类，不按目录时间
猜“最新备份”，也不依赖旧 stage coordinator。

## 凭据与工具

`pg_dump` / `pg_restore` 只接收显式、无内联口令的 PostgreSQL URL、受保护 passfile 和已解析的
工具绝对路径。子进程环境会移除 ambient PostgreSQL/数据库路由变量；原生 stdout/stderr 不进入用户
日志。恢复使用 `--single-transaction --exit-on-error --no-owner --no-privileges --role <owner>`。

## 资格边界

CI 的真实 PostgreSQL recovery lane 会通过生产 complete-generation owner 备份 smoke dataset，验证
manifest/files，再恢复到专用 scratch 库并比较全部 public tables。该证据不能替代正式 Windows
生命周期证据。没有同一 exact-head EXE 在真正干净的本地 Windows VM 完成首装、备份、恢复、重启、
卸载前，项目继续 `QUALIFIED_HOLD`。

禁止把单独 `pg_dump`、手工复制 uploads、只运行 `pg_restore --list`、CI green 或旧源码升级历史称为
正式备份/恢复闭环。
