+++
schema_version = 2
id = "0071"
title = "收据附件的复合权威、崩溃一致性与同代恢复"
summary = "规范化收据 bytes 与 PostgreSQL 中的账本归属、生命周期和预期摘要共同构成有效附件，缩略图仅是可重建缓存"
current_scope = "收据原图上传、受保护读取、清理、完整性巡检、备份恢复和本地文件到未来对象存储的迁移"
date = "2026-07-11"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "data-consistency"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "后端资产、数据库与宿主恢复 adapter 维护者"
verification_owner = "独立数据正确性、安全与恢复 reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "refines"
target = "0003"
scope = "受保护图片不公开暴露之外，补足附件权威、完整性、路径隔离和客户端协议"

[[relations]]
kind = "refines"
target = "0059"
scope = "restore/clone 晋升必须把同代附件校验与实例身份、凭证 sanitation 一起完成"

[[relations]]
kind = "refines"
target = "0066"
scope = "家庭账务事实系统中图片证据、结构化账本事实、缓存和恢复副本的权威边界"

[[relations]]
kind = "depends-on"
target = "0067"
scope = "数据库与附件同代备份、schema compatibility、恢复隔离和 mixed-version contract gate"
+++
# 0071 收据附件的复合权威、崩溃一致性与同代恢复

## [ADR-0071-SCOPE] Context, Scope and Non-goals

小票夹已是家庭账务事实系统。收据图片不是普通上传临时文件：它可能是确认金额、商家、时间和家庭分账的原始证据，
也是 OCR/AI 建议的输入。但图片 bytes 不能单独说明属于哪个账本、是否仍有效或是否已经被有意删除；PostgreSQL 中一行
路径也不能重建丢失的 bytes。只说“PostgreSQL 是唯一真源”会掩盖跨存储数据丢失，只说“文件在就算成功”又会绕过
账本归属、权限、生命周期和完整性裁决。

当前实现已经对请求图片做解码、像素上限和 metadata sanitation，并对实际写入 bytes 计算 SHA-256；文件先写入，随后
创建 Expense，数据库失败时尽力删除文件。它也限制相对路径和账本目录。但当前直接写最终文件，没有 temp/fsync/原子
发布协议；受保护读取只检查路径与文件存在，不重验预期 digest；Python 备份只含 PostgreSQL，计划任务又在另一个时刻
镜像 uploads，没有同代 generation manifest。数据库引用存在但 bytes 缺失、bytes 被改写、数据库 dump 与 uploads 来自
不同代时，系统不能证明附件有效或可恢复。

本 ADR 决定收据**规范化 bytes**、PostgreSQL ownership/lifecycle/expected metadata、缩略图、文件/对象存储、备份和恢复
之间的权威与失败协议。它适用于 Windows 本地文件 adapter，也约束未来 Linux、对象存储、云端或多机器 adapter。
它不把图片内容变成结构化财务事实，不让图片/OCR 自动确认账目，不要求保存上传前原始 bitstream，也不预先实现多 active
writer、通用 DAM 或任意附件系统。

## [ADR-0071-ASSUMPTIONS] Assumptions and Applicability

- 当前受支持拓扑是一套 PostgreSQL、一个 active backend writer 和一个本地 uploads root；宿主可在备份/恢复窗口冻结写入。
- 单个上传受配置的 byte/pixel/dimension 上限约束；附件数量和总量必须由容量观测给出，不能靠递归全盘扫描维持请求正确性。
- PostgreSQL 可以原子提交 ownership/lifecycle；普通文件系统或对象存储不能与数据库做同一 ACID transaction，因此必须使用
  可重试 saga、不可变 object identity、补偿和 reconciliation，而不是假装存在跨资源事务。
- 本地文件 adapter 只在受支持卷/文件系统上承诺原子同目录 rename。若平台不能证明 rename 与 durable flush 语义，adapter
  必须 fail closed 或采用经故障演练证明的替代发布协议。
- OS Administrator 最终可以接管本机数据，是明确残余风险；日常 backend、PostgreSQL、客户端和 OCR provider 仍按最小权限隔离。
- 进入多 active writer、跨区域对象复制、零停机海量备份或监管级原始凭证保全时，必须复审 barrier、fencing、保留和真实性证明；
  不能把当前家庭自托管停机窗口外推。

## [ADR-0071-DRIVERS] Decision Drivers

- 数据正确性：不能把“PG 行存在”“路径存在”“HTTP 200”任一单项冒充可读取、未损坏且归属正确的收据证据。
- 安全与隐私：路径、digest、跨账本文件和 EXIF/metadata 不应泄漏；缺失与越权不能形成枚举 oracle。
- 崩溃与并发：写文件、提交数据库、清理、备份和恢复在任一边界崩溃后都必须停在可识别、可重试状态。
- 可恢复性：数据库与 bytes 必须来自同一受控 generation；恢复要先隔离验证，不能让半恢复实例对外写入。
- 性能：完整性验证是 O(bytes) 的必要成本，但不得每次请求无界加载整图或让全盘 scrub 阻断日常记账。
- 扩展性：本地路径是 adapter 细节；未来对象存储依然遵守相同 owner、digest、状态机、备份与删除语义。
- 操作体验：授权用户必须能区分“主动删除”“存储暂不可用”“证据缺失/损坏”和“正在恢复”，并知道是否可重试。

数据正确性和隐私优先于快速返回；完整性与可恢复性优先于节省一次校验；当全量校验与交互延迟冲突时，使用不可变对象、
有界 verification cache 和后台 scrub 降低成本，不能关闭校验或静默返回未经证明的 bytes。

## [ADR-0071-ALTERNATIVES] Alternatives

- **A. 只以 PostgreSQL 行为权威，uploads 视为可丢缓存**：拒绝。收据 bytes 不能从结构化行重建，丢失后证据永久消失。
- **B. 只以文件存在为权威，数据库可扫描重建**：拒绝。文件名、目录和 hash 不能证明账本 owner、业务引用、删除意图或权限。
- **C. 把每张图片作为 PostgreSQL `bytea`/large object 与引用同事务保存**：跨存储一致性较简单，但会放大数据库、WAL、备份、
  复制和恢复成本，且当前已存在受保护文件存储。没有实际容量/运维证据支持迁移，拒绝作为当前默认；它仍可作为未来 adapter。
- **D. 永久同时保存上传前原始 bitstream 和规范化副本**：取证能力更强，但保留 EXIF/设备 metadata、重复存储和删除负担与当前家庭
  账务产品不匹配。拒绝。请求原始 bytes 是短命 transport input；成功后只有版本化 normalization 输出进入附件契约。
- **E. 采用 PostgreSQL metadata + 不可变规范化 bytes 的复合权威，以 saga/reconcile 和同代 manifest 闭环**：选定。它承认没有
  跨资源 ACID，并把每个失败窗口变成可检测状态，而不把本地文件系统冻结成领域核心。

## [ADR-0071-DECISION] Decision

选择 E。一个有效收据附件是“已授权的 PostgreSQL ownership/lifecycle/expected metadata”与“可按该 metadata 取得并验证的
规范化 bytes”的合取；任何一半都不构成有效附件。缩略图、感知 hash 和客户端副本均为可删除重建的派生缓存。

### [ADR-0071-C01] 规范化 bytes 与 PG 元数据共同构成附件权威

- 上传前原始请求 bytes 只存在于有界处理阶段，不进入权威、备份或导出。解码、方向校正、metadata 移除和必要重编码后的输出
  是 **normalized bytes**；若 normalization profile 判定无需重编码，原 bitstream 也只是作为该 profile 的输出被接受。
- normalization profile/version、SHA-256 expected digest、实际 size、media type、账本 ID、业务 owner、逻辑 asset ID、storage
  adapter/key、生命周期和创建/删除审计必须由 PostgreSQL 权威记录。物理表名和列布局可迁移，本 ADR 不冻结为 Expense 的路径列。
- digest 必须对实际持久化 normalized bytes 计算；感知 hash、ETag、文件 mtime、对象名和原始 filename 都不能替代 integrity digest。
  digest 不能作为授权凭证或跨账本可枚举 ID。
- asset 与 Expense/未来其他业务 owner 的绑定只能由同一服务端命令在账本权限检查后创建或改变；文件 adapter、OCR provider、
  Screen、Web JS、Room 和备份扫描器不能反向认领 ownership。
- 财务金额、商家、消费时间和确认状态仍由 PostgreSQL 结构化事实裁决。图片可作为人类证据和建议输入，但图片缺失不得自动改写
  已确认财务事实；必须显示证据完整性风险并保留审计。

### [ADR-0071-C02] 生命周期和完整性状态必须区分主动删除与损坏

至少使用以下可观察状态；内部实现可有短命 staging/purge job，但不得压扁这些语义：

| 状态 | 必要条件 | 允许行为 |
| --- | --- | --- |
| `complete` | PG owner/lifecycle 有效，normalized bytes 可取得，size/digest 与预期一致 | 授权读取、OCR/AI 输入、备份和迁移 |
| `deleted` | PG 明确记录 actor/reason/time/policy 的逻辑删除 | 新读取拒绝；物理 purge 独立重试并有回执 |
| `missing` | PG 仍预期附件，但 adapter 找不到 bytes | 不得伪装成 deleted/404 成功清理；告警、修复或从同 digest generation 恢复 |
| `corrupt` | bytes 存在但 size/digest/解码或 adapter identity 不符 | 隔离，不提供给用户/OCR/AI；保留诊断和恢复入口 |
| `orphan` | 存储中有对象，但没有已提交 PG owner | 不提供、不按 hash 自动挂账；经 grace/reconcile 后删除或显式修复 |
| `restoring` | 候选 generation 正在隔离恢复/校验，尚未晋升 | listener/write worker 关闭；只允许恢复验证器访问 |

`deleted` 只证明业务上不可再读取，不单独证明 bytes 已物理擦除；必须另有 purge result。普通保留期清理与隐私彻底擦除不是同一承诺：
后者只有在线副本、对象版本、临时文件和所有仍在保留期内的备份均到期/被销毁并留下回执后才能宣称完成。缺失文件、权限错误、
adapter timeout、digest mismatch 或 unlink 失败永远不能通过写 `deleted_at` 被“修好”。

允许的状态转换必须带 OCC/lease 和审计：`complete → deleted` 是显式用户/保留策略命令；`complete → missing/corrupt` 来自完整性
证据；`missing/corrupt → complete` 只允许从 digest 匹配的受信副本修复；`restoring → complete|missing|corrupt` 来自 restore reconcile；
`orphan` 不能直接变成 complete，除非维护者在核对 owner、generation 与审计后执行专用 repair。未经证明的逆转换 fail closed。

### [ADR-0071-C03] 创建采用 durable publish → PG commit → 幂等补偿

在当前单 writer/local filesystem adapter 下，创建协议固定为：

1. 在大小/像素上限内完成 normalization，计算 profile、digest、size 和 media type；请求失败不留下权威 asset。
2. 生成不可猜 asset identity 与账本作用域 storage key；在最终目录同一受保护卷用 exclusive temp 创建，分块写入，flush/fsync
   文件，再用不覆盖既有对象的原子 rename 发布；平台支持时同步目录 metadata。禁止直接写最终可见文件或原地覆盖 complete bytes。
3. 发布后重新 stat/校验 size 和 digest，才在一个 PostgreSQL transaction 中写 owner、expected metadata、`complete` 状态、业务引用、
   idempotency result 和审计；commit 是客户端可见性的边界。
4. 只有能够证明 transaction 已 rollback/未 commit 时，才可幂等删除本次新对象；删除失败留下 orphan finding，由 reconciler 回收。
   连接在 commit/ACK 边界断开属于 **commit outcome unknown**，此时禁止删除对象：必须用预分配 asset identity、业务引用与
   idempotency key 从新的数据库连接回查。已提交且 metadata/digest 匹配则返回首次稳定结果；可证明未提交才转 orphan cleanup；
   仍无法裁决则 quarantine 并停止自动删除，等待 reconcile。进程在 rename 后、commit 前崩溃只产生 orphan，不产生假业务事实。
5. 只有 PG committed row 与已发布对象经同一 identity/digest 对账后才能向客户端确认。响应丢失由同一 idempotency key 返回稳定结果，
   不能再次生成第二个附件，也不能用“补偿删除”制造已提交引用永久缺图。

对象存储 adapter 可以用 conditional immutable put/version ID 替代 temp+rename，但必须在 PG commit 前验证服务端 checksum/回读 digest，
并保留相同崩溃矩阵。对象存储 ETag 不是无条件 SHA-256。任何 adapter 若不能提供不可变发布、唯一 identity、read/stat/delete/list 和
故障注入合同，就不能承载 complete asset。

### [ADR-0071-C04] 删除是逻辑 tombstone 后的可重试 purge saga

- 删除/保留策略先在 PG transaction 中以 OCC 记录 `deleted`、actor/policy/reason、删除 generation、undo/purge deadline 和审计；commit
  后新读取必须拒绝。已在 commit 前取得授权句柄的有界 in-flight 响应可以结束，但不能开始新的读取。
- background purge 使用 asset identity + expected digest 的幂等命令删除 normalized bytes、thumbnail/temp/object versions，并记录每个
  adapter 的结果。存在 undo deadline 时不得提前 purge。失败保持 `deleted + purge_pending/failed`，产生告警并重试；不能改回
  complete，也不能报告隐私擦除成功。
- 若产品允许 retention 内撤销，只有 bytes 尚在、digest 验证成功且业务 owner 仍有效时，才可经 OCC `deleted → complete`；物理 purge
  或相应备份到期后是不可逆边界，UI 必须在命令前说明。已确认财务事实的图片清理不得删除财务行或改变金额。
- 当前“先 unlink、后提交 deleted marker”的路径必须迁到 tombstone-first。旧 binary 不理解新状态时不能与新 schema 同时写；按 [[0067]]
  expand → migrate → capability gate → contract，并为 mixed-version 返回稳定 `upgrade_required`，不能靠 nullable timestamp 猜状态。
- 如果产品宣称隐私擦除在恢复旧 generation 后仍成立，purge/tombstone receipt 必须进入独立于可回滚 generation 的加密、append-only
  erasure journal，并在 listener 开放前重放；或者先销毁所有仍可能含该 asset 的旧备份。没有这两项之一，只能说在线副本已删除，
  不能承诺旧备份恢复不会复活 bytes。该 journal 是恢复约束证据，不得变成日常 ownership 或任意业务写的第二权威。

### [ADR-0071-C05] 每次读取先授权，再按风险验证完整性

- 所有读取先以当前 principal、ledger membership 和业务 owner 从 PG 解析 asset；跨账本/越权统一 404 防枚举。授权后的 `deleted` 返回稳定
  unavailable；`missing/corrupt` 返回可区分且不泄漏路径/digest 的 integrity error；`restoring` 返回可安全重试的 unavailable/503。
- local adapter 必须用 canonical root + handle-based no-follow/open 约束拒绝绝对路径、`..`、symlink、junction/reparse point、非普通文件和
  check/open TOCTOU。普通 API 不返回 storage key、绝对/相对路径或 integrity digest；迁移期旧字段只作 opaque deprecated 值，客户端
  不得拼路径，须经 capability negotiation 退役。
- 每次读取至少验证 state、owner、adapter/object identity、普通文件/对象类型和 size。第一次冷读、metadata 变化、进程重启后的未验证对象、
  OCR/AI/导出、备份、迁移、restore 与 integrity scrub 必须分块计算完整 SHA-256 后才消费 bytes。
- 对不可变且 ACL 受控的对象，可缓存 `(generation, asset_id, object identity, size, mtime/version, digest)` 的成功校验，避免每次展示重复
  O(bytes)；任一键变化、cache TTL 到期、adapter 重连或 integrity event 立即失效。缓存不是权威，删除后必须同步失效。
- digest 计算不得把整图二次载入内存；除 normalization 本身的 decoder 需求外，读取/校验用不大于 1 MiB 的有界 chunk。release benchmark
  记录 cold digest throughput、cached-open p95、scrub I/O 和最大配置图片下的 peak memory；相对上一 verified baseline 回退超过 20%
  必须解释/接受，不能通过降低验证覆盖率变绿。

### [ADR-0071-C06] 缩略图和派生指纹永远是缓存

- thumbnail、perceptual hash、OCR provider 临时副本和客户端图片缓存可删除重建，不进入附件 complete 判据，也不能作为恢复 source of truth。
- 缩略图 key 必须绑定 source asset identity + expected digest + renderer/profile version；源 digest 或 renderer 变化时旧 thumbnail 自动失效，
  不允许通过覆盖同名文件让客户端看见混代内容。
- thumbnail 生成失败不得回滚已经 complete 的 normalized asset 或阻断手工记账；返回原图受保护入口/占位状态并有界重试。源为
  missing/corrupt/deleted 时禁止从旧 thumbnail 推断原图仍有效。
- OCR/AI provider 只得到经当前 principal/后台 capability 授权、完整性已验证且按隐私策略最小化的 bytes。provider cache/上传生命周期
  必须独立记录；识别结果仍是建议，不能把 derived text、置信度或 provider object URL 升格为附件权威。

### [ADR-0071-C07] 数据库与 uploads 备份必须属于同一 generation

可恢复候选由**同一个 generation manifest**绑定，而不是“有一个 dump 加一个 uploads 文件夹”。manifest 至少包含：generation ID、
installation/security-domain identity、ledger scope、schema/Alembic revision、backend/release identity、UTC barrier、PG dump hash/size/list
验证、每个非 deleted asset 的 asset ID/storage adapter+version、expected digest/size/media/profile、对象复制结果、缺失/损坏/排除项、manifest
自身 hash、创建主体和 lifecycle receipt。清单中的敏感 storage key 必须加密/最小化，不进入普通日志或 UI。

manifest 是候选恢复副本的 inventory/evidence，不是在线 ownership 或 lifecycle 权威；在线实例不得根据 manifest 覆盖更新的 PG 状态。
当前 generation 的 PG tombstone/删除审计必须进入 dump 与 manifest 摘要，deleted bytes 不作为 active asset 复制。恢复更老 generation 时，
必须按 C04 重放该 generation 之后的 erasure journal，不能因旧备份中仍有 bytes 就复活已完成的隐私删除。

当前单 writer 可以选择并实机证明下列一种 barrier，不能混用其承诺：

1. **bounded quiesce**：宿主生命周期锁 + PG advisory backup lease 停止 HTTP/background asset mutation，排空 staging，冻结 cleanup，完成一致
   PG dump 与 immutable asset snapshot/校验后才放行；或
2. **snapshot + retention pin**：PG exported snapshot 与存储 snapshot/object version 精确绑定，generation 内对象不可覆盖/删除，直到 manifest
   完成且复制验证通过。

manifest 完成前任何 dump、目录镜像或对象复制只是 partial candidate，不进入“最近有效备份”、不触发旧 generation 轮转。数据库成功但
任一 expected asset 复制/校验失败时整代失败；不得用 `/MIR` 的最终目录形状推断历史同代。备份真实性若要抵抗有写权限攻击者，manifest
必须有存放于备份之外的 detached signature/MAC；只有 ACL+hash 时只能宣称意外损坏检测，不能宣称防恶意篡改。

### [ADR-0071-C08] restore/clone 在隔离域 reconcile 后才能晋升

- restore 目标使用独立目录/database identity，状态为 `restoring`，listener、scheduler、OCR/AI 和普通 writer 均关闭。验证器先验证 manifest
  认证/hash、PG archive、schema compatibility、post-generation erasure journal 和 [[0059]] 的 same-install/clone credential sanitation，
  再逐项回读 normalized bytes。journal 缺失时必须明确报告“旧删除状态未知”，不能静默宣称 privacy-safe restore。
- reconcile 以 PG expected inventory 裁决：匹配为 complete；缺对象为 missing；digest/size/type 不符为 corrupt；清单/存储多出的对象为
  orphan。禁止按文件名、目录、mtime 或 perceptual hash 自动补 owner。所有结果写入 restore receipt，不污染源 generation。
- 财务/schema/身份不变量失败时禁止晋升。只有附件缺失/损坏时，可以由 risk owner 显式选择 degraded recovery：受影响资产保持
  missing/corrupt、UI 与审计持续可见、修复命令受限；不得把它们批量标 deleted 或把该 generation 称为 verified。未作明确选择时 fail closed。
- 晋升绑定目标 database identity、asset root/object namespace、generation、effective credential fingerprints 和 binary/schema capability；切换
  必须原子或可回退。旧 namespace 在新实例通过 smoke + integrity read 前只读保留，不能被 cleanup 提前删除。

### [ADR-0071-C09] 本地权限、隐私与故障域不得随 storage adapter 放宽

- storage key 必须 opaque 且账本作用域化；只有 asset service 能从 PG record 解析。backend runtime 只访问 uploads runtime subtree，
  PostgreSQL service account、普通用户、Web/Android、OCR provider 和其他账本不能列目录或读 sibling。
- 本地 root/subtree/file ACL、owner 和 reparse policy 在启动与 restore 时 fail closed 校验；backend 可读写运行数据不意味着可读恢复材料。
  备份/恢复 helper 使用短命 capability。未来对象存储使用每实例/环境最小 IAM，不共享全局 bucket admin credential。
- normalization 默认去除非业务必需 EXIF/metadata；原 filename、绝对路径、raw bytes、digest、tenant/storage key 和 provider payload 不写普通
  日志、诊断包或 metrics label。高基数 asset identity 只进入受控审计；运行日志使用事件码与不可逆、短期 diagnostic correlation。
- 单个大图/坏图/provider timeout 只失败该 asset；上传并发、normalization、thumbnail、OCR、scrub、backup 和 migration 分别有 queue/配额/
  超时/取消。资源耗尽可以拒绝新上传或暂停派生任务，不能绕过大小/完整性/人工确认，也不能拖垮手工无图记账。

### [ADR-0071-C10] 存储迁移和 mixed-version 先扩展后收缩

- storage adapter 合同只暴露 immutable put、authorized get/stat、idempotent delete、bounded inventory 和 version/checksum proof；领域不能依赖
  Windows path、drive letter、SCM、固定 bucket、ETag 格式或单文件系统。
- 迁移先 expand 新 adapter/key/version 字段和双读能力；按 PG expected inventory 复制 normalized bytes并验证 digest；shadow-read 比较；再以
  capability gate 切新写入和读优先级。旧对象在全部引用、备份 generation、rollback window 和离线客户端协议通过前只读保留，最后 contract。
- 禁止无 manifest 的目录搬移、原地覆盖、由 object listing 回写 PG owner 或把 copy 成功数当完整性。中断后从稳定 cursor 幂等继续，重复 copy
  必须得到同 digest，冲突进入 corrupt/repair 而非 last-write-wins。
- 新 backend + 旧客户端通过受保护 asset endpoint/能力字段兼容；旧客户端不能上传 storage path/hash。新 schema + 旧 backend 若不能理解状态机，
  lifecycle gate 必须拒绝 writer。多机器 writer 在共享 fencing、single-owner reconcile 和 backup barrier ADR 落地前仍不受支持。

### [ADR-0071-C11] 失败矩阵必须保留真实语义

| 故障点 | 可观察状态 | 必须动作 | 禁止动作 |
| --- | --- | --- | --- |
| normalization/size/decode 失败 | 无 committed asset | 删除 temp，返回稳定 4xx | 保存原始坏文件后建 PG 行 |
| temp 写入/fsync/rename 失败 | 无 committed asset 或 temp orphan | fail closed、隔离/回收 temp | 以文件存在宣称成功 |
| final publish 后、可证明 PG 未 commit/进程崩溃 | orphan | grace 后 reconcile/delete | 扫描 hash 自动挂到账本 |
| PG COMMIT 已发送但 ACK/连接丢失 | outcome unknown，可能已 committed | 禁止删对象；按 asset/idempotency 从新连接回查，无法裁决则 quarantine/reconcile | 把连接异常一律当 rollback 并补偿删除 |
| PG 已 commit 但 bytes 丢失/存储不可达 | missing 或暂时 unavailable | 重试 stat、告警、从同 digest 副本修复 | 写 deleted_at、返回空图当成功 |
| size/digest/decoder 不符 | corrupt | 隔离、停止 OCR/导出、恢复/人工处置 | 继续流式返回或重算 digest 覆盖预期 |
| thumbnail 失败 | source 仍 complete | 降级占位/原图、重试缓存 | 降级 source 状态 |
| logical delete commit 后 purge 失败 | deleted + purge failed | 新读拒绝、告警、幂等重试 | 宣称物理/隐私擦除完成 |
| 旧实现先 unlink 后 DB commit 崩溃 | missing | 从同 digest 副本修复或显式接受损失 | 因“本来想删”补写无证据 tombstone |
| PG dump 成功但 asset snapshot/manifest 失败 | invalid partial generation | 保留上一 verified generation，修复后重做 | 轮转上一代或显示备份健康 |
| restore 中任一 mismatch | restoring + findings | 保持隔离，修复或显式 degraded decision | 开 listener/worker 后再检查 |
| OCR/AI timeout/拒绝 | asset 不变 | 记录建议任务失败，手工路径继续 | 修改、删除或确认财务事实 |

### [ADR-0071-C12] 可观测性和操作反馈必须可行动且不泄密

- 结构化事件至少覆盖 `asset_publish_failed`、`asset_orphan_detected`、`asset_missing`、`asset_corrupt`、`asset_purge_failed`、
  `asset_repaired`、`asset_backup_generation_failed`、`asset_restore_reconcile_failed`，记录 stage、adapter class、result、retryability、
  generation/build/schema 和低基数 reason；不记录 path、raw digest、tenant、secret 或 bytes。
- metrics 至少有各状态计数、publish/verify/purge 延迟、orphan age、scrub coverage/age、backup generation 完整率、restore mismatch、queue depth、
  bytes/throughput 和失败率。按 asset/tenant/path 做 metrics label 禁止；账本级详情进入授权 health/audit view。
- 普通用户看到：附件状态、是否影响账务事实、是否可重试/从备份修复、下一步；owner/maintainer 才看到 generation、scrub、容量和 repair 状态，
  仍不直接展示主机绝对路径/secret。后台绝不把 missing 自动变成“已清理”。
- SLI/SLO 在首次 verified 实机基线后写入 evidence profile：新上传 complete 比率、cold/cached read、scrub 最大陈旧时间、verified generation 年龄、
  restore reconcile 正确率和 MTTR。没有连续 measurement 前只能报告 observed，不得在 ADR 中虚构可靠性百分比。

## [ADR-0071-CONSEQUENCES] Consequences

- Good：图片不再被误称为数据库缓存或孤立文件；缺失、损坏、主动删除和恢复中可以区分；崩溃窗口、备份代际和存储迁移均可验证。
- Costs：需要 PG asset lifecycle/metadata、durable file adapter、reconciler/scrubber、同代 manifest、restore 隔离和客户端协议迁移；上传、备份与
  cold read 增加 hash/fsync I/O，恢复时间随总 bytes 线性增长。
- Limits：数据库与 blob store 仍没有跨资源 ACID，短时 orphan/missing 只能靠协议检测与补偿；SHA-256 证明 bytes 与预期一致，不证明收据
  现实真实性。只有 hash+ACL 的备份不抵抗拥有写权限的恶意主体。
- Privacy trade-off：上传前 bitstream/EXIF 默认不保留，降低隐私与存储风险，但不能提供法证级原文件。此代价由 risk owner 接受；若进入
  合规原始凭证场景必须新 ADR，不得静默改 normalization。
- Availability trade-off：known missing/corrupt 不自动删掉结构化账务事实；显式 degraded recovery 可救回其余家庭账本，但必须持续暴露风险。

## [ADR-0071-REVERSIBILITY] Reversibility, Replacement and Retirement

本地文件 adapter、对象存储、表布局、hash cache 和 manifest 格式可按 C10 渐进替换；“PG owner/lifecycle + verified normalized bytes”的
复合权威、missing 不等于 deleted、同代恢复和人工确认边界不可回退。转入 PostgreSQL bytea/large object 时也必须先复制+digest 校验、
双读、generation drill、切写、保留 rollback window，再退役旧对象。

已物理 purge 且所有保留备份到期后，bytes 基本不可逆；normalization 后丢弃的原始 bitstream 也不可恢复。UI/导出/维护命令必须在不可逆
边界前提示。代码回滚只能回到理解当前 lifecycle/schema 的 compatible binary；旧 binary 会把 missing 当 deleted、忽略 asset state 或直接
拼 path 时，宿主必须拒绝启动 writer，不能为了快速回滚破坏证据。

复审/替代触发：附件超过当前容量 profile 导致 barrier 超过维护窗口；需要零停机/多 active writer；对象存储跨区复制；监管要求保存原始
凭证/不可抵赖时间戳；SHA-256 不再满足项目安全基线；或连续 restore drill 无法在目标 RTO 内完成。反向验收：任一 PG 行可在 bytes 缺失/
digest 错误时仍显示完整、任一目录镜像可脱离 generation manifest 被称为可恢复备份、任一缓存/provider 可回写 owner，均证明本决策未成立。

## [ADR-0071-CALIBRATION] Current Implementation Calibration

截至本 ADR 建立时，现行代码与本决策 **nonconformant**，验证状态为 **failed**：

- `backend/app/services/file_service.py::save_upload_bytes` 对 sanitized bytes 计算 SHA-256，但用 `target_path.open("wb")` 直接写最终路径，
  没有 exclusive temp、file/directory fsync、原子 publish 或发布后 digest 验证；Expense 也未权威记录 size、media/profile 和完整状态机。
- `backend/app/services/expense_service/_create.py::create_pending_expense` 在异常/finally 路径会尽力删除 source/thumbnail，这是有价值的
  pre-commit 补偿，但它尚未区分“可证明 rollback”与 commit outcome unknown；COMMIT 已落库而 ACK 丢失时可能删除已提交引用的唯一 bytes。
  当前也没有 stable asset identity/reconcile，因此不能证明 C03，且属于数据完整性 release blocker。
- `backend/app/services/expense_service/_image.py::ensure_image_file` 与 `file_service.resolve_protected_image` 检查删除标记、账本目录和文件存在，
  读取时不比较已存 `image_hash`；当前 API schema 仍暴露 `image_path`/`thumbnail_path`/`image_hash`，客户端字段尚未迁到 opaque capability。
- `backend/app/services/backup_service.py` 的有效备份是单独 `pg_dump`；`backend/scripts/backup_database.ps1` 后续另行 `/MIR` uploads。二者没有
  同一 writer barrier、asset inventory/generation manifest 或逐对象 restore reconcile，因此不能证明 dump 与图片同代。
- 本 ADR worktree 中 `cleanup_service._delete_relative_file_for_db_mark` 已有一个**未提交候选方向**：发现 PG 引用的文件缺失时保持
  `image_deleted_at` unset，并发出脱敏 `upload_integrity_missing` 事件。它只修正“missing 不等于 deleted”的局部语义；在进入主线、通过真实
  PG/故障测试并补全状态机前，不能作为本 ADR 已实现或已验证的证据。

因此当前发布证据不得把“图片路由 200”“pg_dump valid”或上述 worktree patch 当作 C01–C12 成立。实施应按可验证切片推进：先阻止
missing→deleted 与路径泄露，再引入 asset metadata/state + durable publish/reconcile，再完成 generation backup/restore，最后迁移/contract
旧路径字段；每片都维持 PostgreSQL 结构化账本和手工无图记账可用。

## [ADR-0071-EVIDENCE] Verification and Evidence

- **结构/数据库证据（C01–C02）**：Alembic、CHECK/unique/FK 和 service mutation tests 证明 owner、expected digest/size/profile、状态转换、
  OCC 与审计；删除任一 guard/constraint 时测试失败。直接 SQL 制造 missing/corrupt 不能被 cleanup 改成 deleted。
- **崩溃故障注入（C03–C04、C11）**：在 temp create、chunk write、fsync、rename、post-verify、PG flush/commit、response、tombstone commit、
  purge 各点 kill 进程；重启 reconcile 后只能得到无状态、complete、orphan、missing/corrupt 或 deleted+purge finding，不能有假 complete。
- **安全/读取证据（C05、C09）**：真实 Windows junction/reparse、symlink、rename race、跨账本 key、绝对/UNC/`..`、非普通文件和 ACL mutation
  全部 fail closed；普通 API/log/metrics/diagnostic scan 不含 path/digest/EXIF。篡改一个 byte 后下一次强校验拒绝用户/OCR/AI 读取。
- **缓存/性能证据（C05–C06）**：max-size 与并发基准记录 cold digest、cached open、peak memory、scrub/thumbnail queue；cache key 任一分量改变
  必须重新 hash，删除/修复立即 invalidation。关闭 thumbnail/provider 后手工账务和 source asset 仍工作。
- **同代恢复演练（C07–C08）**：运行中并发上传/删除时生成 generation，在隔离 data root + database restore；逐项核对 PG inventory、digest、
  schema、installation identity、credential sanitation 和财务不变量。交换两代 uploads、删除/改写一个对象或篡改 manifest 时不得晋升。
- **迁移/mixed-version（C10）**：local→替代 adapter 中断/重试、dual-read/shadow compare、回滚窗口、旧 client+新 backend、新 client+旧 backend、
  新 schema+旧 binary release matrix；未知 lifecycle/payload 返回稳定 upgrade/conflict，不发生 last-write-wins。
- **运行证据（C12）**：scrub coverage、state counts、orphan age、verified generation age、restore findings 和 purge backlog 有 machine receipt、source
  commit/blob、环境、命令、结果、时间、owner 与失效条件；首次全链路 fault drill 通过前保持 failed。

最低 fault drill 集合：断电式 upload publish、PG commit 后响应丢失、unlink/ACL 失败、DB 行存在而文件缺失、单 byte corruption、backup 中
并发上传/删除、两代备份错配、restore 后旧 credential sanitation、storage adapter migration 中断。独立 reviewer 必须查看原始 receipt，不能
仅凭 generated status 或文档勾选把状态改为 verified。

## [ADR-0071-REFERENCES] References

- [[0003]] uploads 不公开暴露与受保护读取入口。
- [[0059]] same-install/clone 身份与凭证 sanitation。
- [[0066]] 家庭账务事实、证据、意图和缓存的领域边界。
- [[0067]] PostgreSQL schema、mixed-version 和恢复生命周期。
- [PostgreSQL pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html)（一致 snapshot 与并发变更边界）。
- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)（类型、大小、存储隔离与权限）。
- [Python `os.replace` / `os.fsync`](https://docs.python.org/3/library/os.html)（实现原语；durability 仍须按宿主实机故障演练证明）。
- [NIST SP 800-107 Rev.1](https://csrc.nist.gov/pubs/sp/800/107/r1/final)（hash 使用与安全强度背景）。
