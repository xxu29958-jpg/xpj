# 本地 PostgreSQL 验证边界

日常安装的数据与一次性验证数据必须分开。Windows 安装的数据库、角色与生命周期由受管入口负责；当前实现与恢复限制见 [PostgreSQL 运行说明](POSTGRES_MIGRATION.md)。

## 使用现行测试拓扑

测试数据库名、端口配置、实例归属与凭据文件名以 [test_postgres_contract.json](../../backend/scripts/test_postgres_contract.json) 为准。不要照抄历史文档中的端口或内联连接串。

- [start_test_pg.ps1](../../backend/scripts/start_test_pg.ps1) 创建或验证专属测试实例；[stop_test_pg.ps1](../../backend/scripts/stop_test_pg.ps1) 通过归属、进程身份及生命周期锁处理同一实例。不要按 PostgreSQL 二进制路径批量结束进程。
- [write_test_postgres_env.py](../../backend/scripts/write_test_postgres_env.py) 根据显式目标与受保护 passfile 生成测试连接。保留 loopback、认证方式和数据库归属检查，不能从日常 `.env` 猜测测试目标。
- base 库供业务验证，smoke 库供真实 HTTP/Web/Android 消费流程。旧源码恢复原型的专用数据库及环境变量已退役。
- 现有 worker 隔离、租约及 real-db 串行边界由 [run_postgres_pytest_lane.py](../../backend/scripts/run_postgres_pytest_lane.py) 和现有夹具执行。两个独立进程不能把同一个共享库当作各自独占的夹具。

## 迁移与失败恢复

测试中可以在已验证归属的隔离库演练迁移、事务回滚与重试。正式安装的 Fresh helper 和迁移 runtime 有独立的 schema owner、migrator 与运行角色；旧的全库改属主脚本已经退役，不能用单角色旧部署办法绕过现行边界。

失败后检查实际 revision、角色、连接与保存的事实，再判断是否能够重试。既有测试证明对应失败恢复语义，不由“PostgreSQL 支持事务”推定任何被中断操作都已回滚。

当前有界冷备验证与完整恢复资格分开，完整恢复仍为 HOLD。不要把日常安装数据拿来跑源码恢复或测试重置。

## 仍然有效的数据语义

后端只使用 PostgreSQL。连接时区、整数金额与币种精度、OCC 行版本、幂等回执及原件归属按现行 Owner 执行；验证应检查业务结果和失败后的事实，而不是复制 SQL 拼写或增加旧方言分支。
