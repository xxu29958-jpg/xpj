# Ticketbox Windows 数据保护当前边界

## 当前可用入口

正式 Windows Manager 的“数据保护”卡连接既有产品消费者：

- “导入与导出”进入同源 `/web/import`，可导入 CSV、导出已确认流水，也可下载包含历史、关系和原件的可携带账本包；活动／归档账本的 Web、Android、Desktop 下载已经在 #471 资格化。业务出口不包含完整 PostgreSQL 集群、宿主凭据或安装绑定。

诊断包仍在“检查与自救”卡中，且不包含令牌、账本内容或原始日志。

## 不可用能力

当前 Manager 不暴露 `/api/backup`、`/api/backups` 或 `/api/restore` mutation，不出货或调用提权备份/恢复 helper。完整数据集备份、正式恢复以及 repair/upgrade/uninstall 生命周期仍为 `HOLD`，不能作为当前产品能力操作或宣传。

backend 中的 complete-dataset/restore 模块、历史 Windows 脚本、旧 ADR 和旧验收记录只作审计与演进输入；它们不是当前出货 Owner，也不进入 frozen runtime。单独 `pg_dump`、手工复制 uploads、`pg_restore --list`、CI green 或旧源码历史都不能冒充正式备份/恢复闭环。

## 2026-10-01 Beta 冷备整组事前范围（CLOSED）

Goal：在最终合同允许的 Internal Beta Host 范围内，提供管理员主动执行、停机留存和可重复读取核验的冷备，避免宿主成为唯一副本。基线 `7a0b99e4` 的安装命令只有 install/resume/inspect，尚无本组入口。完整备份／恢复 HOLD 不移交给本组。

| 责任与消费者 | 本组退出结果 |
| --- | --- |
| 既有 installation binding、immutable release、生命周期互斥、Windows 服务与 PG | 只读核对正式默认安装、身份、随包工具和无未完成安装；管理员已停止 Backend 与 PG，PG 必须正常关闭。复制期间保持停机，结束前重新核对；不自动启停服务、改变 ACL、角色、schema、restore epoch 或安装绑定。 |
| 冷备归档 | 包含整个 pgdata（含 WAL／空目录）、attachments、app 设置、machine 身份与凭据、对应程序与工具链。新文件独占创建，Admin/System 私有 ACL 在写入前成立；拒绝已有目标、源目录内目标和重解析路径，不覆盖或删除任何现存文件。 |
| 完成／失败／再读取 | 逐文件摘要、大小与完整目录集合；源变化或中断不能得到完成清单。最后重新读取源并核对停机状态，再写完成清单并落盘；独立 verify 命令重读所有归档内容。失败文件保留为未完成，不自动删旧副本，不把重试变成续写半份归档。 |
| Manager 实际入口与说明 | 继续复用已交付的业务出口及脱敏诊断；在数据保护卡提供可读的停机冷备／核验步骤及恢复边界，服务不可用时仍能看说明。GUI 不提权、不增加高权限 HTTP/helper 入口。 |
| 业务材料与恢复边界 | 保留原金额、schema、dataset/install identity、原件和凭据；手机／浏览器未同步 intent 不在宿主副本中，不能以冷备代替同步或清空设备。归档核验不代表正式恢复，当前无原安装覆盖、异机接管或 restore-epoch 发布命令。 |
| Evidence | 小型真实文件失败／变化／中断／损坏反例；实际 Windows ACL、新文件拒绝和源不变；隔离的真实 Windows PG 冷副本可读取原业务行与集群身份，原件摘要一致；实际 Manager 说明；exact source／独立 main 既有门禁与随包 CLI 核验。日常安装和数据不参与演练。 |

实现限于现有受管 Windows 工具的冷备命令、归档读写、直接 Manager 说明与必要验证。没有新生命周期状态机、数据库表、服务、计划任务或恢复发布者。该归档含私密业务和宿主凭据，不是可发给支持人员的诊断包；转存介质应保留访问保护。它不包含 Windows 服务注册、用户凭据库或外部 Tunnel 配置，也不是系统镜像。完整 restore、repair、重装、升级和卸载继续 HOLD。

平台依据：[PostgreSQL 17 文件系统备份](https://www.postgresql.org/docs/17/backup-file.html)要求完整集群且服务器停机；[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)提供独占新建和创建时安全描述符。源码、真实 PG、随包 EXE、完整安装恢复与最终 RC 分别资格化。

整组收口：#484 最终源 `44a26fb0` 的 CI、CodeQL、三个实际 Connected 分片、默认多端旅程及安装版冷备旅程均通过。独立合并 main `1561fb5e4354829c2b65352b2b7d7ed2ed33a467` 的 CI `36836388461`、CodeQL `36836388518`、实际 Connected `36836388516`、默认多端旅程 `36836388464` 与冷备旅程 `36837903789` 也全部通过。主干自身 Setup SHA-256 为 `c93c8a7a88b71f0424a0809a99d273d5b4107e7c11b6326f954afeebe050250f`；实际随包 EXE 完成 4,743 文件／408,328,743 字节的复制和读回，验证运行中拒绝、中断残件拒绝、新私有归档、覆盖拒绝、独立 PG 副本读取及原服务重开后事实相同。1234 分草稿、币种绑定、schema、角色、dataset/cluster identity 和原件 SHA 已核对。当前手动冷备及读取核验可以使用；完整恢复和其他既定 HOLD 保持，最终全产品 RC 尚未完成。
