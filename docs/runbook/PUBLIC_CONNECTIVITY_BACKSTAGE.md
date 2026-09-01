# 公网连接 Backstage 运维说明

本文只说明 Desktop Manager 的 `公网连接` 只读状态面。它帮助操作者区分
Windows 服务、Cloudflare Edge、Ticketbox 源站、公网产品和公网边界；它不负责安装、
接管或修复 cloudflared。

上位施工合同是 2026-09-01 Gmail《Ticketbox 公网连接 Backstage / cloudflared
受管接入｜GPT 主提示词 + 完整施工合同》。本页不替代该合同，也不改变
[Cloudflare Tunnel 配置说明](CLOUDFLARE_TUNNEL.md) 中现有人工部署拓扑。

## 操作入口

Manager 卡片标题为 `公网连接`，副标题为 `由 Cloudflare Tunnel 提供`。它只提供三个动作：

| 动作 | 会做什么 | 不会做什么 |
|---|---|---|
| 刷新状态 | 异步读取精确 Windows 服务、固定 loopback cloudflared 诊断端点和现有 Ticketbox 源站状态 | 不读取产品凭据，不访问公网，不改变服务或进程 |
| 完整检查 | 在后台执行刷新，并对已配置 HTTPS 公网地址做有界 GET、产品身份和边界验证 | 不上传、不写业务数据、不跟随重定向、不调用 Cloudflare 账号 API |
| 导出诊断 | 导出关闭式 allowlist 中的状态码、时间、版本、计数和布尔匹配结果 | 不导出 URL、token、UUID、账号/设备标识、路径、argv、日志或配置 |

卡片不得出现安装、启动、停止、重启、修复、更新、UAC 或 token 管理按钮；这类能力属于
后续受管生命周期阶段。

正式安装态的公网地址 authority 是 Backend 服务拥有的 runtime setting，不是 Manager 的
`ManagerConfig.public_base_url`（该字段在 installed mode 中故意为 `None`）。Backend 先将地址
规范化，再通过仅限 loopback、安装身份受 attestation 保护的 installation-health v3 合同投影；
Manager 只在进程内将它交给完整检查。该地址不进入 Manager 稳定状态 JSON、日志或诊断包。
只有 installation-health 明确给出 `local_only` 才表示未配置；Backend authority 不可用时地址状态是
`unknown`。完整检查缓存还绑定到当时的精确地址与 authority state，地址被修改、清空或失去 authority
后不会复用上一地址的公网/边界结论。Backend 已规范化并证明可用于手机入口的非 loopback IPv4/IPv6
HTTPS origin 也属于合法消费值。

## 如何读状态

`overall` 只由后端状态模型按固定优先级生成，UI 不重新裁决：

| overall | 含义 |
|---|---|
| `unsafe` | 公网边界泄露了禁止路径，或受保护身份发生冲突 |
| `unknown` | 证据过期、所有权未配置/外部未受管，或证据不足 |
| `offline` | 已受管服务缺失、停止或失败 |
| `connector_unavailable` | connector 不可用或 tunnel 身份不一致 |
| `origin_unavailable` | 本机 Ticketbox 精确源站不可达或身份不一致 |
| `public_unavailable` | 公网端点不可达或不是预期 Ticketbox 产品 |
| `degraded` | 正在连接、部分连接或只证明匿名健康可达 |
| `healthy` | 受管所有权、服务、Edge、精确源站、认证公网产品和安全边界全部当前有效 |

不要只看 `overall`。卡片同时保留这些独立事实：

- `ownership`：是否由当前 Ticketbox 安装合同受管；
- `service`：精确 `Cloudflared` Windows 服务状态；
- `connector`：固定 loopback 诊断端点证明的 Edge 连接状态；
- `origin`：精确 Ticketbox 本机源站状态；
- `public`：公网健康与认证产品状态；
- `boundary`：禁止公网路径是否确实被拒绝；
- `freshness`：完整证据是否仍在有效期内。

Cloudflare Edge 健康只证明 connector 到 Edge 的连接存在，不证明 Ticketbox 源站或公网产品健康。
同样，发现外部 cloudflared 进程或诊断端点只能得到 `external_unmanaged`，不能升级为
`managed` 或 `healthy`。
精确服务确实不存在且诊断端点也不存在时才是 connector `unconfigured`；SCM 读取失败而又没有诊断证据时是 `unknown`。

## 刷新、时效和并发

- Manager 每 10 秒安排一次本地只读刷新；已有刷新在途时不重叠安排。
- 状态 API 永远只读缓存，不在控制请求线程中访问 SCM、HTTP、DNS 或 Windows 凭据。
- 当前完整证据最长有效 60 秒；年龄只按进程内 monotonic elapsed time 计算，UTC 时间戳只用于展示和诊断。系统时间跳变不会提前过期或延长旧证据。
- 每次请求使用递增 generation；旧请求晚完成也不能覆盖更新请求。
- 若两个刷新请求发生重叠，后一个请求会在调度前销毁可复用的公网/边界证据；只有非重叠的本机刷新可以沿用上次完整检查。
- 任何可能改变 Backend 或 WinCred ProductSession 真相的操作都会打开 fail-closed 突变窗口：窗口两端都销毁旧公网/边界证据并推进 generation，窗口内不调度刷新。即使 Backend 已提交但响应丢失，或 WinCred 保存/删除失败，旧 bearer 和中间态检查也不能回写。若完成态恢复位仍存在，后续完整检查（包括 Manager 重启后）只接受与恢复证明派生 successor 一致的主凭据。主凭据尚未成为该 successor 或旧凭据撤销未结清时，新的绑定不得删除/覆盖恢复位；只有 Backend 明确以终局 401 拒绝 activation replay 时才可清理这颗不再可激活的证明。即使清理后 predecessor 仍在轮换宽限期，auth-check 的 `credential_state=grace` 也只能得到 `reachable_unverified`，不能重新变绿。
- 完整检查有 8 秒总期限、最多 16 个固定 GET，每个响应最多 8 KiB。
- Manager 退出会取消排队工作并使用有界等待；新进程从 `stale + unknown` 开始，不继承旧缓存。
- Manager UI 对状态 fetch/body 与后续产品会话/账本读取使用同一个 2 秒刷新期限；Manager 状态 reject/non-2xx、状态 body reject，或链路任一阶段永久 pending 至超时，都会丢弃旧公网投影并显示 `状态未知`。立即返回的产品会话/账本 fetch、HTTP、JSON body 或消费 schema 失败都会清除旧账本选项、隐藏产品管理入口、把产品卡降级为“暂不可验证”并释放刷新锁，但不会否定已经成功取得的 Manager 公网投影。产品角色只接受 `owner`、`member`、`viewer`；未知角色按 schema 失败处理，不直接显示。

## 只读排障顺序

1. 点“刷新状态”，等待 `in_progress=false`，先看 `ownership`、`service`、`connector` 和 `origin`。
2. `external_unmanaged` 表示只发现外部连接；不要把它当成 Ticketbox 已接管，也不要从本页手工改服务。
3. Edge 健康但 `origin=unreachable` 时，结论仍是源站不可达；Edge 连接数不能替代源站证明。
4. 已配置公网 HTTPS 地址时再点“完整检查”，分别看 `public` 与 `boundary`。
5. `reachable_unverified` 只证明匿名健康端点，或 bearer 仅处于 rotation grace；只有本地 Desktop app session 元数据与公网
   `/api/auth/check` 完全一致且 `credential_state=current` 才是 `authenticated_reachable`。
6. `boundary=violation` 优先按 `unsafe` 处理；不要反复重试来覆盖该结论。
7. 需要协作排查时导出诊断包；不要附加 cloudflared 原始日志、配置、命令行或凭据。

读取失败、超时、重定向和超大响应都保持显式 `unknown`/失败状态。收到 HTTP response 后，即使声明为 JSON 的 body malformed 或顶层 schema 不是 object，也保留真实 HTTP status，仅把 payload 视为不可用：2xx 健康响应因此判为错误产品，401/403/404/405 仍按明确拒绝参与边界判断。任何一种都不会被宽泛异常处理伪装成健康。

## 隐私边界

公网 bearer 只可由完整检查的上层协调器从现有 Windows Credential Manager session 取得，并且
只进入 HTTPS `Authorization` header。它不得进入 URL、浏览器、日志、异常、状态投影、诊断包、
文件、环境变量或子进程 argv。

cloudflared tunnel/connector UUID、连接明细、服务 ImagePath、argv、SCM 原始配置、公开域名、
证书、账号/设备标识和 Ticketbox 数据都停留在各自读取边界内，不进入 Manager 稳定投影。

## 2026-09-01 真实 Windows 只读观察

- 精确 `Cloudflared` 服务：`missing`；
- 所有权：`external_unmanaged`；
- 固定诊断端点：`connector=healthy`，安全计数 `4`；
- Ticketbox 源站：`unreachable`；
- 当前源码配置公网地址：`unconfigured`，所以公网与边界实网检查不适用；
- overall：`unknown`，稳定 code 为 `external_connector_unmanaged`；
- 本机不存在本任务可安全归属的 cloudflared 测试夹具，stop/recover 观察为 N/A，未改变 SCM、
  Scheduled Tasks、进程、文件、注册表、凭据、网络或 tunnel 配置；
- Manager 重启回归证明新 Provider 从 `stale + unknown` 开始，不继承旧 `healthy` 缓存。

## Stage 2 HOLD

以下责任没有随本页开放，继续保持 `MANAGED_PUBLIC_CONNECTOR = HOLD`：

- cloudflared 下载、安装、升级、执行与版本供应链；
- Windows 服务注册、启动、停止、重启、修复、失败恢复与卸载；
- tunnel token 获取、轮换与 Machine Secrets；
- Cloudflare 账号 API、DNS、Public Hostname 和远端 ingress 变更；
- UAC helper、installer、repair/restore/upgrade/uninstall 与 Release Manifest/receipt 写入；
- 受保护 connector expectation 的生成、持久化与生命周期所有权。

在 Stage 2 获得独立 Owner 裁决和施工合同之前，不得把这些动作塞进当前 Manager 卡片或只读
Provider。
