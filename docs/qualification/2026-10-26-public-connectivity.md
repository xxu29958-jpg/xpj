# 受管公网接入资格记录（2026-10-27）

受管服务、普通 Manager、四个固定 Lifecycle 动作及旧入口退役已实现，适用的公网专项资格已闭合。Android 正式 Release 真机已完成扫码、上传、真实会话续期和续期后鉴权读取原图。本记录明确区分实际执行、源码复用和保留限制。iPhone 未实机验证，iPad 按既有裁决后补；R2/U1/C1 继续 HOLD，`INTERNAL_BETA_READY=false`。

## 构建与复用边界

| 对象 | 精确来源 |
| --- | --- |
| 实际干净安装并恢复数据的基线 | [PR #678](https://github.com/xxu29958-jpg/xpj/pull/678)，main `8c7e0e5a8ef469d8603e4657fd1480fd14d696fc`；Setup SHA-256 `b3cbe2078477ab2736e5cd2d9d54601acd17eeb3552c51be1ee2f77d1472131b` |
| 最后运行源码 | [PR #679](https://github.com/xxu29958-jpg/xpj/pull/679)，main `b9d5658ce97a84760173c655c08df45f0285bd93`，tree `b77b4d949a6a23187dfe622d852ed38a3473ebda` |
| 最后 Windows 发行件 | CI artifact `12643704414`；Setup SHA-256 `09c3b8c755b20dd63098b6f820665c28695c74e05d6b434fda43e165b2831285`；Manager EXE SHA-256 `7b5aa39834993f8afd28a19922bd12bf4306970072b1474ea76416f67ab17e64` |
| 真机 Android | 同一 main 的实际 CI grayRelease，version 1.2.0 / 10200000；持久证书签名 APK SHA-256 `f54cb83b218e76f12620ca8255ff0dcc30787ecd4150afb52f25f77a1548b867`；非 DEBUGGABLE |
| 目标环境 | Windows 11 Pro 10.0.26200 x64，Hyper-V 2 核 / 4 GB，PostgreSQL 17.11，schema `20261023_0002`；Android 16 / API 36 的 Xiaomi 24129PN74C 真机 |

`8c7e0e5a` 到 `b9d5658c` 仅改一处未知 Edge 原因说明及 runbook 的 30 秒检查预算。Backend、Windows distribution 和 Android 子树完全相同。最后 Setup 的 provenance、118 项 Manager 源文件和 66 个载荷文件已核验；最后 Manager 在原安装上以普通权限实际运行，但没有把整个最后 Setup 再做一次干净安装。安装、数据与服务证据按该明确差异复用，不能改写为最后 Setup 的新执行结果。

较早 `83fdc0d7721607098ee92d874f90716230ea8240` 的无人值守、持久暂停和中断续办证据，只复用逐文件核验未变的 75 项事务、Lifecycle 与运行责任源码。后来改动的 Web 上传、秘密输入、HTTP 探测和 UI 路径分别补验；不会把先前整体绿测直接移给新 SHA。

## 合同 Q01–Q15

下表的证据文件名指向本专项保留的私有实际记录，不在仓库公开凭据、用户身份、设备标识或内部路径。

| 项目 | 实际结果与边界 | 主要证据 |
| --- | --- | --- |
| Q01 首装 | 干净目标实际安装、R1 恢复；普通 Manager 配对、按需 UAC、原生掩码录入、重开 UI 及同操作读取。固定 EXE、服务身份和秘密 ACL 已核对。 | `public-installed-main-result.json`、`q01-manager-owner-main.json` |
| Q02 公开面 | 实际 Edge 的 16 个产品/边界 GET 通过；Funds/Income 的 8 组路由授权成功、匿名拒绝。Owner/Admin、诊断、私有及原图目录不公开。 | `q03-two-real-instances-current-result.json`、`q02-business-routes-main.json` |
| Q03 身份 | 两个实际已安装 Backend 同时运行，同名称、同数据集的不同安装代际负控不绿；旧实例真实会话被新公网拒绝。重定向和错误页另由既有契约覆盖，未制造混合负载均衡流量。 | `q03-two-real-instances-summary.json` |
| Q04 Android | 正式 Release 真机扫码、上传一张合成测试图、真实续期后在普通 UI 重新加载原图通过。仍为原上传 claim、原账单、Pending 和原件摘要；新凭证在旧凭证宽限期结束后实际使用，同账号/设备/账本保持，匿名原图请求返回 401。首次上传为蜂窝加既有 VPN；续期和随后原图读取为蜂窝、无活动 VPN，全程无 ADB 转发。续期触发方式见下文。 | `q04-runtime-completion-20261027.json`、`phone-q04/install-main-b9.json`、`phone-q04/server-after-original-read.json` |
| Q05 Web | 真实公网登录/上传；提交成功但回复丢失后，原 key 和原文件重试仍只一笔事实；实际退出和会话到期回登录，原稿保留。测试 relay 已停止，原 ingress 已恢复。 | `q05-retry-facts-main.json`、`q05-recovered-ui-main.txt`、`q05-session-expiry-main.json` |
| Q06 无人值守 | 关闭 Manager、注销、重启未登录、断网恢复、最多三次 SCM 故障恢复及手动重连已有实际证据并核验源码可复用。客机不支持睡眠态，睡眠/唤醒未验证。 | `q06-*-r10.json`、`r10-final-main-recovery-reuse.json` |
| Q07 暂停 | 暂停跨重启保持 Disabled/Stopped；其他 connector 仍可提供公网时，UI 如实说明本机已暂停而公网仍可达。 | `q07-paused-reboot-r10.json`、`q07-paused-external-online-main.json` |
| Q08 凭据 | 错 Token、正确替换、旧 secret 清理；真实远端轮换后旧连接仍在线，隔离后旧 Token 重启失败，再经普通 Manager 配置新 Token 恢复。产品身份未更换。 | `q08-wrong-token-main.json`、`q08-old-replica-isolated-main.json`、`q08-rotated-new-connected-main.json` |
| Q09 中断/并发 | Token 输入取消无提交；持久切点注入和一次实际 VM 断电后，仅原 operation/请求/当前安装续办。connector-only 不挡住本地 Backend，不产生第二业务提交。 | `q09-host-interruption-r10.json`、`q09-same-operation-resumed-r10.json` |
| Q10 权限 | 普通用户读取秘密和请求 SCM 修改权限均被拒绝；进程、EXE、安装归属与固定诊断端点核对。替换路径、外部同名服务和请求注入等由对应 Windows 负控/契约覆盖。 | `q10-ordinary-main.json`、既有供给与服务契约记录 |
| Q11 备份/R1 | 活跃公网配置后的真实冷备 v2 不含 Tunnel Token；干净安装实际 R1 保留数据集、Owner、事实及原件，新安装代际独立；旧合法 v1 仍可验证。 | `q11-restored-facts-main.json`、`public-installed-main-result.json` |
| Q12 R1 三端 | 旧 App、Web 和 UploadLink 失效；新 Web 和真机接入恢复后的数据集，旧离线意图没有提交；双实例证明旧代际不能混入。新 Android 已在同身份下实际续期并读取原图。 | `q12-local-rejection-main.json`、`q12-public-rejection-main.json`、Q03–Q05 |
| Q13 迁移/移除 | 精确移除只清理本机受管服务与秘密，外部副本和本地 Backend/PG 保持；历史事实、6 个旧原件/缩略图摘要不变。完整 immutable 文件集合与摘要通过，既有冷备 5,393 文件再验证通过，没有新建备份。 | `q13-removed-external-online-main.json`、`q13-preservation-comparison-current.json`、`q13-immutable-current.json`、`q13-existing-cold-verification-current.json` |
| Q14 iPhone | 未实机验证；按 Goal 边界独立保留，不能用 Web、API 或 Android 证据替代。 | 未执行 |
| Q15 维护/诊断 | 固定 cloudflared 2026.10.3；实际 UI 导出仅允许字段，23 组秘密/标识表示扫描零命中。发行责任人、支持窗口与维护期限明确；未声明独立热更新或完整 U1。 | `q15-native-diagnostics-main.json`、`q15-support-review-main.json` |

## 旧入口与用户步骤

当前宿主写操作只有 Manager 到既有 Lifecycle 的四个固定动作。普通使用从 Manager 设置一次，按需 UAC 后输入 Token；运行后不用保持 Manager 打开。暂停、重连、替换和移除在同一入口完成，服务命令、常驻终端、秘密文件与原始日志不再成为日常操作步骤。Cloudflare 远端账号、DNS、ingress 和 Token 管理仍属于明确的远端责任。

实际安装中检查了 11 个旧手动入口：已删除或明确拒绝执行，不能再次创建外部 connector；检查前后服务不变，见 `vm-legacy-retirement-main-8c7e0e5a.json`。旧 Owner 公网管理没有恢复。状态卡先给结果和下一步，服务/Edge/源站/边界细节收在展开区；未知原因不猜成网络故障。中断后只继续核实过的原操作，不能扩展为任意恢复或自愈。

## 失败、维护与剩余收口

最后源码的 [CI 40309987478](https://github.com/xxu29958-jpg/xpj/actions/runs/40309987478) attempt 2、[CodeQL 40309987483](https://github.com/xxu29958-jpg/xpj/actions/runs/40309987483) 和 [Android Connected 40309987460](https://github.com/xxu29958-jpg/xpj/actions/runs/40309987460) 均成功。CI 首次浏览器 DevTools 启动失败保留；没有通过改断言、加长时限或改产品代码取得重跑成功。

最后 Manager 已实际显示产品身份和安全边界通过；这些结果带 60 秒时效，不是永久绿灯。另一次实际完整检查只确认产品身份、边界检查未完成，UI 保持 unknown。保留该失败/部分结果以及最初 Python 默认 UA 探测失败，不用后来成功覆盖历史失败。

Q04 首次续期夹具超时，已恢复原配置字节。它退出了测试手机会话，造成再次扫码；此失败和二维码过期记录保留。用户重新扫码接回原设备身份后，采用同证书签名的临时 Android instrumentation 调用**已安装 Release 内已有的续期协程**：正式客户端自行产生请求证明、经实际公网执行 refresh、校验响应并通过原安全存储保存新凭证。没有修改 APK、手机时间、服务器配置或会话字段，没有注入 Token 或写入伪造回执。自然经过续期时间窗口的调度未等待到期，不能把这个触发夹具写成普通界面的自动计时执行证据。

服务端实际产生一次续期回执，手机冷启动保留新连接；旧凭证宽限期结束后，从普通 UI 点击“查看原图”，经历加载状态并显示原图。原上传 claim、账单、Pending 和 50,008 字节原件摘要保持，匿名读取返回 401。发行 Backend 按设计关闭访问日志，本次用真实客户端显示、现有续期回执及新凭证最后使用记录互证，不虚构 HTTP 访问日志。临时测试组件已卸载，Wi-Fi 恢复，正式安装包摘要和原服务器配置不变。测试组件第一次触发早于 Application 初始化而失败，第二次等待实际初始化完成后成功；该首轮失败同样保留。

维护按 [固定版本的维护责任](../runbook/CLOUDFLARE_TUNNEL.md#固定版本的维护责任)执行：仓库所有者负责跟踪、核准和发布替代版本，最晚 2027-07-21 完成替代资格；上游支持变化或安全问题取更早期限。取得资格前不开放独立更新入口。

手机临时组件、Web relay、外部测试连接器及双实例负控的临时网卡已清理。第二 VM 已正常关机且无网卡。探针目录的删除在 Owner 明确授权后仍被自动审批拒绝；271 个测试文件（2,659,258 字节）留在该停用 VM 内，不能记为已删除，实际证据副本完整保留。最新处置见 `q03-second-instance-cleanup-20261027.json`。这项清理限制与未实测的睡眠/唤醒、iPhone、后补 iPad 独立记录；数据盘、既有冷备、原开发 WIP、失败证据和日常数据继续保留。仓库当前状态与唯一私有交接按最终合并结果同步，不把文档合并代替运行资格。
