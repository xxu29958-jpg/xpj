# PostgreSQL 运行与验证边界

小票夹当前仅使用 PostgreSQL。Windows 安装由安装器及 Lifecycle Coordinator 建立数据库、角色和数据身份；本文用于定位现行实现与检查，不提供对已安装数据的手工改属主、灌库或恢复命令。历史 SQLite 迁移与旧源码部署方式见 [ADR-0041](../DECISIONS/0041-postgresql-engine-migration.md)，不作为当前安装步骤。

## Windows 当前路径

- Fresh 安装调用 [现行 schema helper](../../backend/app/database/_fresh_schema_upgrade.py)，由 [受管迁移 runtime](../../backend/app/database/_managed_postgres_migration_runtime.py) 执行事务、角色边界和失败恢复。
- 运行角色、schema owner 与 migrator 各守现行权限；启动时检查 schema 与 dataset authority。不要用旧 `ticketbox` 单角色操作或全库 owner 修复脚本替换这些边界。
- 数据库和原件属于安装的数据根。故障排查从 Manager 的诊断与导出入口开始，参见 [Windows 服务 Runbook](WINDOWS_SERVICE_RUNBOOK.md)。

## 冷备与恢复限制

当前有界冷备保留；[既有安装产物演练](../../distribution/windows/qualification/cold_copy_drill.py) 验证受管停止后创建归档、原件字节、独立 PostgreSQL 副本可读，以及原安装重新打开后的事实不变。

这些结果不代表完整恢复、异机接管或升级回退。完整恢复仍为 HOLD，范围见 [备份任务边界](WINDOWS_BACKUP_TASK.md)。旧 `dataset_maintenance_cli`、完整 generation writer/restore 原型及其源码 CI 演练在独立 RC 前清理中退役：它们未出货且没有产品入口，不继续作为当前能力的验证。

既有备份 inventory 的只读兼容保留，仅报告记录及年龄；没有重新校验 payload 时不会声明完整性成立。清理不删除历史归档或用户数据。

## 隔离 PostgreSQL 验证

测试拓扑由 [test_postgres_contract.json](../../backend/scripts/test_postgres_contract.json) 单独定义，保留业务用的 base 库和真实消费流程用的 smoke 库。旧恢复原型专用库不再创建。

本机启动源码后端前，按 [本机 PostgreSQL 验证边界](postgres-local-safety.md) 显式设置 `DATABASE_URL`。启动测试实例或生成测试变量并不会自动改写当前终端的应用数据库地址。

- 真实 smoke 运行 bootstrap、上传与 OCC 确认；Web/Android 联调使用同一隔离 smoke 库。
- ordinary 与 real-db lanes 验证现行业务、权限、迁移、事务回滚与失败恢复；云端检查绑定实际源码。
- 显式 loopback、受保护 passfile、数据库归属及进程租约仍为测试隔离边界，不把已安装数据用作测试夹具。

这些检查证明各自的现行行为，不单独代表独立清理里程碑、RC 或完整恢复完成。
