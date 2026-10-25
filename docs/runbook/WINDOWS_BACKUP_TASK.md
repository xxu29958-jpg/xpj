# Ticketbox Windows 数据保护当前边界

## 当前可用入口

正式 Windows Manager 的“数据保护”卡连接既有产品消费者：

- “导入与导出”进入同源 `/web/import`，可导入 CSV、导出已确认流水，也可下载包含历史、关系和原件的可携带账本包；活动／归档账本的 Web、Android、Desktop 下载已经在 #471 资格化。业务出口不包含完整 PostgreSQL 集群、宿主凭据或安装绑定。

诊断包仍在“检查与自救”卡中，且不包含令牌、账本内容或原始日志。

## R1 同环境受控恢复

R1 复用安装包中的 Lifecycle、数据库维护程序与 Manager。仅支持原安装已隔离、完整停机 `.tbxcold` 副本及可信安装包的组合：相同 release id、schema 与语义版本，PostgreSQL 随包目录逐文件相同；目标是没有 Ticketbox 服务、数据或绑定的干净 Windows 环境。它不覆盖原安装，不执行归档中的程序，不迁移 WinCred/Keystore/Tunnel，不执行 schema 升级。R2 异机恢复、U1 升级失败恢复与 C1 独立加密副本仍 HOLD。

管理员在隔离目标上运行匹配的可信 Setup；摘要必须来自此前保管的冷备回执。`SOURCEISOLATED=YES` 表示已停用原安装，避免同时接受新账务：

```powershell
& '.\Ticketbox-Setup-1.2.0.exe' /RESTORECOPY='D:\Recovery\selected.tbxcold' /RESTORESHA256='<此前保管的64位SHA256>' /SOURCEISOLATED=YES
```

恢复先逐字节核验副本、目录、安装身份及程序兼容性，再复制到新的私有数据根。原副本始终保留；旧安装绑定、服务注册与 ACL 不会被采用。机器数据库凭据重新生成；原安装的受保护恢复材料必须与数据库内唯一 installation-owner claim 匹配，且对应账号仍是有效 Owner。管理员权限本身不授予业务身份；缺失材料或角色不成立时保持候选关闭。

身份重建事务保留 dataset、账务事实、历史、原件和账本成员角色，更新 installation/client generation，递增 restore epoch 并记录源副本标识。原会话、设备、上传链接、邀请与配对能力失效，旧签发尝试不能恢复会话。数据库 signing/audit identity 保留。新的短期配对材料仅沿安装程序的受保护结果交付给原 Owner，随后通过普通 Manager/客户端重新连接。

核验启动只开放安装健康端点，后台任务和业务请求均关闭。原件、角色、schema、代际和服务健康通过后才发布正式 binding；提交恢复操作并重启服务后开放业务。失败保留源副本、候选和现有 Active Operation，阻止 Fresh/resume 接管；不要删除 `active.json`、清空目录或反复运行安装来绕过失败。诊断后使用新的干净隔离目标重新恢复。

恢复点仅包含冷备停机时已经到达宿主的内容。恢复后先核对旧账务、历史和原件，再从普通产品入口记录一笔业务并核对结果。手机/浏览器尚未同步的草稿及 Outbox 不在冷备中：保留原设备、原稿、key 和原身份，重新配对后核对新代际，旧意图不得自动重放到新代际；先按已有回执核对已提交结果，再由用户明确续办。不得用清空客户端或重建同一笔交易来“修好连接”。备份以后曾在宿主提交但未进入副本的事实也不会自动出现。

发行资格必须绑定实际 Setup/源码 SHA、源冷备摘要、停机截止时间、目标 Windows/PG 组合及真实业务续写证据。源码测试或安装健康成功不等于 R1 整组通过；未演练的组合不在已验证范围。苹果快捷指令实机验收仍单独后补。

## 其他不可用能力

当前 Manager 不暴露 `/api/backup`、`/api/backups` 或 `/api/restore` mutation。R1 使用上述离线管理员安装入口，不增加高权限 HTTP 通道。完整恢复 GUI、其他恢复组合以及 repair/upgrade/uninstall 生命周期仍为 `HOLD`。

未发布的 complete-dataset/restore 原型及专属源码演练已经退役；历史 Windows 脚本、旧 ADR 和旧验收记录只作审计背景。既有有界冷备和只读库存保留。单独 `pg_dump`、手工复制 uploads、`pg_restore --list`、CI green 或旧源码历史都不能冒充上述 R1 的完整恢复证据。以下 #484 记录保留其原始冷备范围，不覆盖本次 R1 授权。

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
