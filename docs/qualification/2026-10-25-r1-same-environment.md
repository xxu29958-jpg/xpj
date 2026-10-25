# R1 同环境完整恢复资格（2026-10-25）

R1 在下述组合中已完成从完整冷备到真实业务续写的恢复。范围来自用户当日授权；R2 异机恢复、U1 升级失败恢复、C1 独立加密副本继续 HOLD。iPad 验收单独后补，iPhone 实机未验证；`INTERNAL_BETA_READY=false`。操作入口见 [Windows 数据保护](../runbook/WINDOWS_BACKUP_TASK.md)。

## 实际构建与恢复点

| 对象 | 本次实际身份 |
| --- | --- |
| 恢复实现 | [PR #675](https://github.com/xxu29958-jpg/xpj/pull/675)，独立 main `f8191b5112acc79943d75e67a0a4b1dd79158488`，tree `dfbe05e5256ff04e4e015fdffc85405a1529fe95` |
| 实际 Setup | CI artifact `12595740559`，`Ticketbox-Setup-1.2.0.exe` SHA-256 `45adb67ce6d8ceaa9575dc598fcbaf186cc4963a81d3d6ab2d3a5f76fbd97ebd` |
| 完整冷备 | 源 `edad37ef78fb83cffd5bf02a5e1baef82fe02457`，SHA-256 `1484b41c23e25f7f2e9f7d2c2ef9c69e0bcb58b9340a54c525c1d71571f296b6`；727,117,283 字节，5,376 个文件 |
| 已验证组合 | Windows 11 Pro 10.0.26200 x64；2 核、4 GB 的隔离 Hyper-V VM；随包 PostgreSQL 17.11；release 1.2.0；schema `20261023_0002` |
| 恢复点 | PostgreSQL 日志时区 Asia/Shanghai；2026-10-25 10:24:24.744 至 10:24:24.808 的停机检查点，完成 LSN `0/23D3790`；已核验正常停机的集群控制状态 |
| 原 Android 消费者 | `edad37ef` grayRelease，签名 APK SHA-256 `edadfd5c68560a704d62b0def3aa3979f2ac71146f3daa9da0dd72f0468a2357`；Android 16/API 36 x86_64 模拟器；保留原应用数据 |

源盘不挂载，原安装不启动；目标为新的干净隔离候选。逐字节核验完整冷备与随包 PostgreSQL 后由实际 Setup 恢复，没有手写数据库、导入凭证或用 API 替代客户端操作。新 installation/client generation、生效 binding、epoch 从 0 到 1、原 dataset 保留均已核对。未执行 schema 迁移。原 Owner 的有效角色及恢复材料由现有数据库权威确认。

## 通过的真实结果

- 恢复前后核对选定业务事实及其历史、角色和附件：2 个账号、2 个账本、4 个成员关系、5 笔原账单、3 个往来、3 笔还款、1 个提议、2 个预算、4 个预算修订、8 个资金变动以及 4 个原件/缩略图文件均保持。外币原额与本位币金额保持。该比较是选定逻辑事实集合；完整副本另有逐字节核验，不能把两者说成全表逻辑转储。
- 普通用户的 Manager 使用安装交付的新配对材料进入原 Owner 的账本；普通 Web 打开原外币账单及两张原件。实际 Windows ACL 拒绝普通用户写程序 manifest、读取数据库口令和私有冷备，均未读写内容。
- 保留原数据的 Android Release 真实显示旧绑定失效，用户退出后通过 Owner 页面生成的 QR 和原生相机连接恢复后的账本。未清空数据、注入 token 或重签旧 intent；旧设备仍撤销，新设备归属原 Owner。隔离 QA TLS 转发连接真实 Backend，仅用于无网卡 VM 的客户端验证，不声称公网 Tunnel 或实网资格。
- 原队列的 4 行（含 1 笔 16.80 元未发送手记）在负例、退出、重连和重启后保持原内容/身份/key/状态；新代际下显示隔离，旧未发送业务在服务端为 0。历史已完成队列行也保留。隔离说明的后续窄修正明确：同一设备恢复仍须核对账本身份，服务器恢复前的操作不会自动发送；没有改变队列或身份协议。
- Android 普通手记入口提交 23.40 元餐饮一次，得到已确认账单和既有回执；Web 与桌面流水均可打开同一笔账单。数据库仅新增 1 笔账单、1 个对应回执。正常关闭并重启宿主、冷启动手机后仍只有这 1 笔新事实，原事实/历史/原件及隔离队列保持。
- 正常宿主重启后 Backend/PG 由原服务身份自动启动，binding 摘要保持、健康请求成功、Active Operation 已归档；Manager 保存的会话直接进入原账本，再打开新账单。

## 失败反例及来源边界

错误摘要和恢复中断实际运行在 PR 最终源 `85f911d37b9573bdf4a3a333187680da2aa1ce21` 的 Setup（SHA-256 `ba3b1e388786226f0cf44e56fe2bafe523436ac6b51d530fb6309e6f53fdf7d1`）；它与上述独立 main **源码树相同**。完整正向恢复与重启使用的是 main 自身 Setup，不能把负例也写成该二进制执行。

- 错误冷备摘要被拒绝，未建立数据、binding 或服务；原冷备摘要保持。Setup 已先展开可信程序载荷，这不等于开放恢复候选。
- 在 durable prepared 且 PG 已运行、binding 未发布时终止本次 Lifecycle：候选及 Active Operation 保留，Backend 停止、无 HTTP 写入口、无 binding，原冷备保持。
- 中断候选正常重启后，PG 仍按已注册的 Auto 服务运行且仅 loopback 监听；Backend 为 Manual/Stopped、无 HTTP。再次运行 Setup 被拒绝，未绕过或删除 Active Operation，源冷备和旧 Android 队列保持。此证据不宣称可原地续修；失败处理按 runbook 使用新的干净目标。

执行中保留的探针/环境失败：初版负例探针错误要求程序目录不存在、要求 PG 停止；随后按实际生命周期契约修正观察，未改产品断言。登录自动输入过快、Android 启动时一次 SystemUI 等待提示、Web 提交后旧 CDP 连接失效、桌面探针错误等待首页等均保留原记录；后续读取产品实际状态，未重复业务提交。此前 PR 的 Edge DevTools 启动失败经本机实际用例通过及原门禁正常重跑通过；不据此断言环境根因已修复。

## 门禁与尚未覆盖范围

独立 main `f8191b51` 的 [CI 40183407110](https://github.com/xxu29958-jpg/xpj/actions/runs/40183407110)、[CodeQL 40183407062](https://github.com/xxu29958-jpg/xpj/actions/runs/40183407062) 和 [Android Connected 40183407061](https://github.com/xxu29958-jpg/xpj/actions/runs/40183407061) 全部通过，Connected 三个实际分片均执行。Planning 成功但未选择的旅程不计作已执行；上面的 R1 实际安装/消费者证明单独保存于私有验收目录。

本记录冻结上述 Setup 和原 Android 消费者的实际结果。后续仅文案/文档变更需独立核对其实际构建与受影响消费者；不得把新源码 SHA 自动套到旧二进制上，也不因窄修正重复制造完整恢复矩阵。

尚未验证其他 Windows/PG/schema/硬件组合、任意磁盘损坏/断电点、真实 Android 硬件和真实公网接入。本次候选是隔离演练，未替换日常安装。冷备不含恢复点之后的宿主提交，也不含端侧未发送内容；必须保留原设备并先核对原回执/已入账结果，不能自动重放或清空旧 intent。R1 通过不授予其他 HOLD 项或全产品 RC 资格。
