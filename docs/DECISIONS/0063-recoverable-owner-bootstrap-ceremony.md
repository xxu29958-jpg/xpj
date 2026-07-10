+++
schema_version = 2
id = "0063"
title = "可恢复 Owner Bootstrap：确定性凭据、全局串行化与关闭窗口"
summary = "以家庭 owner 身份 claim 为核心，隔离可恢复创建、可撤销子凭证和安装交接"
current_scope = "main 未实现；overlay 已有 HMAC/DB 锁/listener recovery/handoff，但精确恢复、并发撤销、凭证解耦和 handoff 父目录 ACL 审查失败"
date = "2026-07-10"
decision_status = "accepted"
implementation_status = "partial"
verification_status = "failed"
decision_type = "security-identity"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "identity + Windows installer 维护者"
verification_owner = "独立 security/concurrency reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0047"
scope = "owner bootstrap secret 的一次性/可恢复语义和安装交接"

[[relations]]
kind = "depends-on"
target = "0028"
scope = "loopback owner 边界与公网拒绝面"

[[relations]]
kind = "depends-on"
target = "0045"
scope = "持久签名 key、占位符拒绝和启动 fail-closed"
+++
# 0063 可恢复 Owner Bootstrap：确定性凭据、全局串行化与关闭窗口

## [ADR-0063-SCOPE] Context, Scope and Non-goals

安装器通过 `POST /api/bootstrap/owner` 创建第一套 owner 身份、admin token、UploadLink 和 Android
pairing code。旧语义把 HTTP bootstrap secret 描述为“成功后立即消费，再用必定 401”。这无法处理
最危险的正常故障：数据库已经 commit，但 HTTP 响应或本地凭据文件写入丢失。随机凭据已经只存 hash，
此时既不能读回原明文，又不能安全创建第二套身份，安装会永久卡死。

`main@0f1092e625` 仍使用随机凭据和“已消费即 401”的旧路径；未提交 installer overlay 才转向
domain-separated HMAC、PostgreSQL advisory lock、listener 暴露隔离/轮换与 owner handoff marker。
这些 overlay 组件不能冒充主线，也尚未组成正确的家庭身份 ceremony：恢复会延长 UploadLink，有些
并发撤销不争用同一锁，而且一个 owner claim 仍与 admin token、上传入口和配对码同时成败。

本 ADR 把**家庭 owner 身份 claim**而不是“首次上传工具的三件套”写成权威核心，并明确可撤销子能力、
恢复窗口、网络边界与安装交接之间的责任。

## [ADR-0063-ASSUMPTIONS] Assumptions and Applicability

- 空安装只允许一个初始 owner identity claim；默认账本和 bootstrap device 可以在同事务创建，但
  UploadLink、移动端 pairing 和后续 owner 转让/成员邀请不是 owner 身份成立的必要条件。
- 安装器能持有 SYSTEM/Admin-only secret 并固定访问 loopback listener，但 loopback peer 本身不是授权。
- PostgreSQL 可提供 transaction-scoped advisory lock；多进程/不同 secret 必须由 DB 串行，而非进程内锁。
- 若未来取消 HTTP bootstrap，替代路径仍必须保留 committed-but-unseen 恢复、凭证隔离和 ceremony close。

## [ADR-0063-DRIVERS] Decision Drivers

- 任何响应丢失都不能创建第二个 owner/ledger/device 或悄悄扩展既有 bearer 的权限/寿命。
- owner claim 重试必须恢复同一身份和同一已提交结果；可撤销的 UploadLink/pairing 是有独立
  idempotency 与交付状态的子能力，撤销或过期不能让 owner claim 失效，也不能被恢复流程复活。
- 两个不同 secret 的并发请求也只能有一个全局胜者。
- secret claim、owner 身份创建和消费记录必须处在同一 PostgreSQL 事务；子能力的创建/交付状态必须
  各自原子且可重试，不能用一个“大结果 envelope”把不同生命周期绑死。
- loopback 不是授权依据；Cloudflare connector 也可能表现为 loopback peer。
- 安装器只应在固定 loopback listener 身份可证明时发送 secret。

## [ADR-0063-ALTERNATIVES] Alternatives

### [ADR-0063-ALT-A] A. 随机生成后只显示一次

响应丢失后不可恢复，拒绝。

### [ADR-0063-ALT-B] B. 明文凭据长期落数据库

恢复简单，但扩大数据库泄露面，并破坏现有 hash-only 凭据模型，拒绝。

### [ADR-0063-ALT-C] C. 用安装 secret 做 domain-separated HMAC，数据库 claim-once

可解决 committed-but-unseen，但若一个 claim 同时派生 admin token、UploadLink 和 pairing code，任一子
能力撤销/过期都会使整个 owner 恢复失败，且恢复代码容易误延长 bearer。仅作为 overlay 的过渡机制，
不选作永久家庭身份边界。

### [ADR-0063-ALT-D] D. Owner claim-once + 分离的子能力交付状态机

选定。安装 secret 只锚定一次 owner identity claim 和最小恢复能力；UploadLink、pairing 与后续设备
凭据是独立、可撤销、可重新签发的 child ceremony。各自使用稳定 operation ID/receipt，数据库只保存
hash 与状态，不保存派生明文。这样既能恢复响应丢失，也不会让上传入口决定家庭 owner 身份是否有效。

## [ADR-0063-DECISION] Decision

### [ADR-0063-C01] 协议版本与派生

secret 必须至少 32 个 UTF-8 字节。installer overlay 的 Python 与 Windows PowerShell 5.1 使用同一
HMAC-SHA256 v1 协议；以下 context 只是在其受支持迁移期内不可原地改写的 wire contract，不是领域
核心必须永远生成三种凭据的理由：

```text
ticketbox/bootstrap-owner/v1/admin-token
ticketbox/bootstrap-owner/v1/upload-key
ticketbox/bootstrap-owner/v1/pairing-code
```

- admin token = `tbx_` + digest 的无 padding base64url；
- upload key = `upl_` +独立 digest 的无 padding base64url；
- pairing code = 独立 digest 对 `10^8` 取模并左补零到 8 位。

三个 context 必须域分离；不能用同一 digest 切片，也不能从另一个派生凭据继续派生。后续解耦协议
必须新增版本，显式区分 owner claim、最小恢复能力和每个 child ceremony；不得给 v1 字符串换含义。
协议字符串、HMAC 算法与 PowerShell transport 属于安装适配层，领域不变量只是“claim 唯一、结果
可恢复、子能力可独立撤销且恢复不增权”。

### [ADR-0063-C02] 全局 Owner 初始化只能发生一次

每次 bootstrap 事务先取得固定 key 的 PostgreSQL `pg_advisory_xact_lock`。该锁覆盖 secret claim、
历史身份检查、所有 identity rows 创建以及调用方 commit，保证不同 secret 也不能同时穿过空库检查。

`BootstrapSecretConsumption.secret_hash` 的插入与身份创建共享一个事务；失败必须整体 rollback，不能
“烧掉 secret 但没建成身份”。是否已经初始化以**任何历史 `AuthToken` 行**为准，不只看 active token；
撤销历史不能把数据库重新伪装成空安装。

同一 ceremony 尚未关闭时，所有会创建、轮换、撤销、消费或失效 bootstrap-bound token/link/code、
bootstrap device 或 owner membership 的写路径，都必须先取得同一顺序的全局锁并在锁内复验目标行。
overlay 目前给 bootstrap、pairing、部分 credential mint/rotation 加了 advisory lock，但普通 device/
UploadLink/token revoke 路径并未全部接线；单边加锁不能构成串行化。锁协议必须有并发 schedule 测试，
不能仅证明两个 bootstrap 请求互斥。

### [ADR-0063-C03] Owner claim 与 child capability 分离恢复

owner claim 的精确语义如下：

```text
first valid secret + empty identity store
  -> claim secret and create one owner/account/default-ledger/bootstrap-device identity in one transaction

same secret after committed-but-unseen response
  -> return the same committed claim and its immutable delivery receipt

different secret after any identity history
  -> bootstrap_already_initialized; never create another owner identity

child UploadLink/pairing/admin delivery is revoked or expired
  -> owner claim remains closed and valid; recovery never resurrects or extends that child

undelivered child response is lost
  -> retry that child operation ID and return the same committed child result, or explicitly start a new
     issuance after retiring the old child; never mutate expiry invisibly
```

每个 child recovery 必须验证自己的 account/device/ledger binding、用途、状态和 operation ID；跨绑或
撤销必须 fail closed。owner claim 的恢复不应以 UploadLink/pairing 仍 active 为前提。任何 recovery
都不得延长已有 UploadLink/admin token 的 expiry；过期 pairing 也不得原地延寿。确需继续交付时，先
保留旧 row 的 expired/retired 事实，再以新 operation ID 创建新 child capability。

overlay 的 `_completed_bootstrap_result()` 仍要求 admin、UploadLink、PairingCode 三者同时存在并有效，
而 `_recover_completed_rotation()` 会把同一 UploadLink 的 `expires_at` 重写为“从当前时刻重新计算”。
这既不是 same-result recovery，也把 owner 身份与上传/配对能力绑死，属于本 ADR 的已知不符合项。

### [ADR-0063-C04] 恢复窗口由安装完成动作关闭

当前窗口不是固定 wall-clock TTL，而是一个安装 ceremony：

1. 安装器把随机 bootstrap secret 写入受保护 `.env` 并启动后端；
2. 只向固定 `http://127.0.0.1:<port>/api/bootstrap/owner` 发请求；
3. 本地持久化并复读验证 owner claim/delivery receipt；各 child capability 的 receipt 独立；
4. 重写 `.env`，移除 `HTTP_BOOTSTRAP_SECRET`/启用开关；
5. 重启后端并再次通过 startup acceptance。

在第 3/4 步之前崩溃，repair 可用同一 secret 恢复同一结果；第 4/5 步完成后 HTTP surface 回到默认
disabled，旧 secret 不再是运行时可用凭据。未来若改成 TTL，也必须保留 committed-but-unseen 恢复，
不能退回“首次响应丢失即永久失败”。overlay 已加入 `owner-handoff-pending`，由 Inno 完成页实际读取
后才清理交付 marker；这是交互回执，不等于 owner claim 与三个 child credential 已正确解耦。

### [ADR-0063-C05] 网络与 listener 身份

HTTP endpoint 默认禁用。启用时必须校验 `X-Bootstrap-Secret`，不能把 client IP/loopback 当权限。
安装器固定禁用系统 proxy、禁止 redirect/query/userinfo/fragment，并在请求前后证明：SCM 后端服务为
Running，Shawl 和后端 listener 的 PID、父子关系、创建时间与受保护 executable 路径未变化。

HTTP 异常后若 listener 身份也变化，视为 secret 可能暴露的安全失败，立即停止重试。成功响应还必须
严格匹配本地派生的 admin/upload/pairing 值，响应大小有界且 UTF-8 严格解码。

目标契约是：listener 后验身份失败必须先写入受保护 compromise state、立即关闭 HTTP bootstrap，并使
该 secret 永久不能被自动 repair 复用。若数据库可能已经 commit，必须走可信本机维护路径隔离暴露
能力；在无法证明是否 commit 前不得继续自动 bootstrap。

installer overlay 已实现该方向：先持久化 exposure recovery intent/启动互锁，把 `.env` 切到无旧
secret 的隔离态，停后端，以 maintenance action 在 PostgreSQL 事务中轮换，再用 replacement secret
恢复；repair 会幂等续做。它仍只是候选实现，且当前 rotation 的撤销集合和生命周期边界过宽：一个
owner claim 同时改写 admin token、UploadLink、pairing，并扫描撤销同 owner/邀请派生的其他凭据；普通
revoke 路径又未全部争用同一 advisory lock。正确目标是撤销**可证明属于暴露窗口的 capability**，保留
owner 身份与不在该窗口内的家庭成员事实，不能用“宁可全撤”掩盖缺失的 issuance provenance。

### [ADR-0063-C06] 凭据交接的当前边界

installer overlay 把 `owner-bootstrap.txt` 与 `owner-handoff-pending` 精确限制为 SYSTEM/
Administrators；Inno 完成页读取内容，要求管理员显式确认，随后由持有机器生命周期锁的脚本删除两者并
验证消失。这比把长期 bearer 留在 app 目录强，也覆盖 over-the-shoulder UAC 的当前管理员桌面交付。

但 overlay 把两文件和 `installer-recovery-required.json` 放在 `DataRoot\app`，同时给 backend 虚拟服务账户
对该父目录可继承 FullControl。受保护子文件 ACL 能阻止 backend 读取明文，却不能收回父目录已有的
`DELETE_CHILD`/create/rename 能力；backend 在安装器读取前已重启，因此失陷或错误服务可删除/替换交付路径，
造成凭证不可见、marker 消失或 repair DoS。该结构不满足日常 runtime 与交付/恢复域分离，不能因子文件 ACL
精确而称为已隔离。

边界仍须明确：这只是未提交的 Windows adapter，主线尚无该能力；完成页一次显示同时暴露 admin、
UploadLink、pairing 三种不同生命周期的凭据，交互确认也不能证明用户已把每种能力安全导入对应客户端。
后续应按 child ceremony 分别展示/确认/销毁，并让标准用户只获得其需要的设备配对能力，而不是整套
owner/admin/upload bearer。不能为方便交接而放宽整个 `app` 目录 ACL，也不能把 GUI、二维码、mDNS 或
Windows 管理员会话写成领域核心必须存在的机制。

目标 Windows adapter 必须把 handoff、handoff receipt 与 installer recovery marker 放到生命周期锁同级的
SYSTEM/Administrators-only sibling；backend 对父目录也没有 read/write/delete/rename。若 backend 必须看到“恢复中”状态，
只能读取不含 secret、不可由其修改的最小 guard projection，不能接触承重 receipt 本体。

## [ADR-0063-CONSEQUENCES] Consequences

Good：DB commit 后丢响应可恢复同一 owner claim；跨运行时输出可验证；并发 secret 不能创建双 owner；
撤销 UploadLink/pairing 不再定义 owner 是否存在。Bad：协议和交付状态更多，child capability 需要各自
idempotency/receipt；bootstrap secret 在 ceremony 完成前仍是高敏恢复材料，必须保护 `.env`、缩短窗口
并完成后重启关闭。overlay 现有三凭据大结果、UploadLink 延寿和不完整 revoke locking 必须修正，不能
因 exposure rotation/handoff 文件已出现就降级为普通债务。

本 ADR 只修订 [[0047]] 的“一次性 secret 用后失效”表述，不改变 [[0045]] 的 per-install CSRF key
决策；bootstrap secret 仍不是长期 CSRF 密钥来源。

## [ADR-0063-CALIBRATION] Current Implementation Calibration (dual baseline, 2026-07-11)

`implementation_status=partial` 仅说明 overlay 已有大量候选实现；`verification_status=failed` 表示它没有
满足本 ADR 的身份/子能力边界。主线与 overlay 必须分栏阅读。

| Capability | `main@0f1092e625` | uncommitted installer overlay / audit result |
| --- | --- | --- |
| 32-byte minimum + domain-separated HMAC | not implemented；随机凭据 | implemented，PS/Python vector 有本地测试 |
| PostgreSQL global bootstrap lock | not implemented | bootstrap/rotation/pair/mint 已部分接线；普通 revoke 未全部共享锁，故并发协议 failed |
| different-secret owner exclusion | only process/row checks | implemented candidate；尚无已合并运行证据 |
| same-secret committed-but-unseen recovery | consumed secret returns 401 | candidate implemented for v1 three-credential envelope |
| recovery preserves exact expiry/result | not implemented | **failed**；rotation replay 重写 UploadLink expiry，pairing recovery 也可改 expiry |
| owner claim independent from UploadLink/pairing | not implemented | **failed**；恢复要求 admin/upload/pairing 同时存在、active、cross-bound valid |
| revoked/cross-bound recovery fail closed | partial | code checks exist；完整 mutation/concurrent-revoke matrix 未证明 |
| listener ownership + proxy bypass + post-validation | not implemented | implemented candidate |
| exposure intent/quarantine + maintenance rotation | not implemented | implemented candidate；撤销集合缺 issuance-window provenance，且与并发 revoke 未完整串行 |
| administrator handoff marker + plaintext retirement | plaintext file only | **failed**；子文件 ACL 已收紧，但父 `app` 目录给 backend FullControl，可删除/替换 handoff/recovery marker |
| least-privilege child handoff | not implemented | not implemented；仍一次展示 admin/upload/pairing 全套 bearer |

## [ADR-0063-REVERSIBILITY] Reversibility, Replacement and Retirement

可以替换 HMAC context、HTTP transport 或交接 UI，但 v1 context 不能原地改写；新版本必须能识别旧消费
记录并显式迁移/关闭。claim-once 与“same operation 只恢复同一结果”基本不可逆，因为回退会重新打开
双 owner 或响应丢失 brick 风险。v1 三凭据 envelope 必须通过新协议的 adoption/retirement 显式拆分，
不能原地把旧 secret 解释成另一套凭据。退役 bootstrap surface 前必须证明所有 fresh/repair 路径已有
等价 owner claim ceremony 和独立 child handoff。

复审触发：需要多 owner 初始化、跨机器远程 bootstrap、listener identity 无法可靠证明、或 compromise
恢复演练无法撤销所有派生凭据。上述变化必须新 ADR，不得扩 HMAC context 配置袋。

## [ADR-0063-EVIDENCE] Verification and Evidence

- 在 DB commit 后、HTTP 响应前故障：重试返回完全相同的 owner claim/delivery receipt，row count 不
  增加，任何既有 admin/upload/pairing expiry 均不改变。
- UploadLink/pairing 撤销或过期后，owner claim 仍保持 initialized；重试 owner claim 不复活、不延寿、
  不替换该 child。新 child issuance 必须使用新 operation ID 并留下旧 row 的 retired 事实。
- 两 session 两个 secret 并发：只创建一套 identity；失败方不能留下消费记录。
- recovery 与 admin token/UploadLink/device/membership revoke 在每个语句边界组成 schedule matrix：不存在
  “响应报告 active 但提交后已被并发 revoke”“revoked capability 被 rotation 改写复活”或死锁。
- 对单个 child 的 principal 停用、cross-binding 或 revoke：该 child recovery fail closed 且不生成替代品；
  不得把 child 失败误报成 owner identity 不存在。
- mutation coverage 必须分别改绑 UploadLink 的 account/device/ledger、PairingCode 的 account/ledger，
  并分别停用 Device/owner membership；每种同-secret 恢复都要 401，且所有 identity/credential row
  count 与值不变。当前尚缺这组完整矩阵，不能用单一 admin-token revoke 测试代表全覆盖。
- Python 与 PowerShell 5.1/7 对固定 vector 逐字节一致。
- listener 在请求中途替换：installer 停止重试且输出不含 secret/响应 body；repair 必须拒绝复用原
  secret。若模拟“可能已 commit”，只撤销可证明属于暴露窗口的 capability；owner claim 与窗口外家庭
  身份事实保持不变。
- ceremony 完成并重启后：endpoint 默认 404 disabled，旧 secret 不再可调用。
- 标准用户 + 独立管理员 UAC handoff：不读 data root 也能只取得所需 child capability；完成后无长期
  bearer 明文残留，且不向普通成员展示 owner admin/upload 全套凭据。
- 用真实 `NT SERVICE\<backend>` token 在 backend 运行前后尝试 read/delete/rename/create-replacement：对 handoff、handoff receipt、
  recovery marker 和其父目录全部拒绝；SYSTEM/Admin helper 持生命周期锁时仍可读写/销毁。仅 protected child ACL 通过、
  但父目录 `DELETE_CHILD` 仍存在时测试必须失败。

反向验收：响应丢失后创建第二个 owner；recovery 延长 bearer expiry；撤销 UploadLink/pairing 导致 owner
claim 变成不可恢复；并发 revoke 绕过 advisory lock；listener 身份变化后 repair 仍复用 secret；或旧
`.env` 随 SCM 重启重新开启 bootstrap，任一发生即证明安全 ceremony 失败。overlay 已命中 expiry、
凭证耦合、revoke locking 和 handoff 父目录删除权四项，故 verification 是 `failed`。

## [ADR-0063-REFERENCES] References

- [[0045]] CSRF signing key 与占位符 fail-closed。
- [[0059]] same-install restore / clone 安全域和凭证 sanitation。
- [PostgreSQL advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS)
- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
