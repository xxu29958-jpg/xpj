# Windows 运行说明

## 正式安装

通过正式安装包安装后，打开小票夹管理器。Backend 与 PostgreSQL 沿既有 Lifecycle 管理，
公网连接在管理器中完成设置、暂停、开启、重新连接及移除。完整账户侧准备与旧连接交接见
[公网连接说明](CLOUDFLARE_TUNNEL.md)。关闭界面、注销用户不会成为后台运行的前提。
电脑睡眠、关机或断网期间不能保证外部访问，本产品不自动修改电源策略。

| 需要完成的事 | 正式入口与结果 |
| --- | --- |
| 第一次连接公网 | 保存公网地址 → 设置公网连接 → 一次 Windows 授权与原生凭据输入 → 自动检查 |
| 暂时关闭公网 | 暂停公网；确认已暂停后，重启仍保持暂停，本地账本可用 |
| 恢复或有限重连 | 开启公网，或在异常时重新连接；沿用当前配置和产品身份 |
| 操作被中断 | 重开管理器；按当前记录继续同一操作，或关闭明确的未完成配置 |
| 更新凭据、移除连接 | 连接详情；暂停状态保持，本机移除不冒充远端撤销 |
| 排查失败 | 查看当前原因、完整检查、导出诊断；不要求用户查进程或操作任务计划程序 |

普通界面只读状态与非秘密结果。固定 Lifecycle 短时提权完成主机动作，凭据不经过浏览器 HTTP、
操作记录或普通冷备。SCM、固定参数、服务账户与 DACL 均核验；普通观察以受信载荷、完整 own-process
服务配置和稳定的 SCM PID／loopback 监听 PID 建立归属。普通用户不需要打开虚拟服务账户的进程。
状态不是“进程存在即在线”；Edge、源站、产品身份、公开边界与证据时间各自有含义。

正式安装不使用 `TicketboxCloudflareTunnel` 登录任务。旧源码运维脚本检测到正式安装或
`TicketboxBackend`、`TicketboxPg`、`TicketboxCloudflared` 服务后，会在动作前拒绝。
已有外部任务不会被自动删除；由原管理工具完成专属目标交接。不能按通配名称批量停服务。

## 外部源码手工环境

以下只保留给**没有正式安装的小票夹源码环境**。它们不能作为正式安装的备用控制入口。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_backend.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_backend.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\restart_backend.ps1
```

`install_windows_tasks.ps1` 只创建源码后端登录任务和可选的每日边界检查任务。
它不再发现、启动或创建 cloudflared 服务／任务，也不读取现有进程的启动参数。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -SkipBoundaryCheck
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_windows_task_status.ps1
```

需要边界检查时去掉 `-SkipBoundaryCheck`；可用 `-BoundaryCheckTime 04:30`
和 `-BoundaryLogRetentionDays 7` 指定时间及日志保留期。任务结果只说明该探针，不能代替公网业务资格。
`diagnose_ticketbox.ps1`、`check_service_status.ps1`、`show_server_status.ps1` 仅诊断此外部环境；
正式安装请在管理器查看状态。`ensure_ticketbox_runtime.ps1` 只启动源码后端并抽查端点，
不会启动 Tunnel，也不因健康端点可达就承诺手机可用。

源码任务的移除仍由 `uninstall_windows_tasks.ps1` 在此外部环境执行；它按明确任务名处理，
不适用于正式安装，不触碰远端 Cloudflare。共享任务或连接须先由所有者确认影响范围。
