+++
schema_version = 2
id = "0064"
title = "Windows 安装器构建 Provenance：本地快照证据与上游信任边界"
summary = "区分本地 payload 完整性、actual-input binding、上游真实性与最终发布 attestation"
current_scope = "main 未实现；overlay 已有 staged inputs、固定 toolchain、真实 ISCC CI 和最终 hash，仍缺上游真实性、签名与 clean release/E2E"
date = "2026-07-10"
decision_status = "accepted"
implementation_status = "partial"
verification_status = "unverified"
decision_type = "dependency-technology"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "Windows release 工程维护者"
verification_owner = "独立 supply-chain reviewer + release CI"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0047"
scope = "构建 provenance、代码签名和未签名 Windows 验收叙述"

[[relations]]
kind = "depends-on"
target = "0010"
scope = "依赖版本、许可证、维护状态和人工升级审计"

[[relations]]
kind = "depends-on"
target = "0062"
scope = "安装生命周期所消费的 release config、payload 和最终 artifact identity"
+++
# 0064 Windows 安装器构建 Provenance：本地快照证据与上游信任边界

## [ADR-0064-SCOPE] Context, Scope and Non-goals

[[0047]] 后来的实施附录曾把 frozen backend、PostgreSQL、Shawl 和 Inno 的版本/Git SHA/SHA-256
manifest 全部写成“尚未实现”。`main@0f1092e625` 的确仍只有存在性检查；未提交 installer overlay
已经生成/验证两层 schema-v3 `BUILD_PROVENANCE.json`，并加入 immutable-ish staging、固定 toolchain、
真实 ISCC workflow 和最终发布单元 hash。必须同时保留这两个事实：overlay 让旧“均未实现”表述过时，
但在合并和云 CI 运行前不能冒充主线证据。

反方向的风险同样存在：有 manifest 不等于上游发布者真实性、可复现构建、代码签名或最终 installer
attestation。需要把四个概念拆开：

1. **snapshot evidence**：在某一检查时点，本地枚举文件的内容与 hash 对得上；
2. **actual-input binding**：构建工具实际读取的不可变输入与 manifest 一致；
3. **upstream authenticity**：这些 vendor/compiler 确由声明的上游发布；
4. **release attestation/signing**：最终安装器由受信构建生成并能由接收者验证。

## [ADR-0064-ASSUMPTIONS] Assumptions and Applicability

- 当前构建在 Windows 上使用 PyInstaller、PostgreSQL bundle、Shawl 和 Inno ISCC，输入跨 Git/source/vendor。
- SHA-256 只能证明比较对象相等，不能单独证明发布者、下载来源、构建隔离或签名信誉。
- 开发 dirty build 允许用于验证，但正式 release 必须有单独 clean/tagged policy 和最终 artifact identity。
- 若未来迁移 MSIX/Store/Linux packages，仍需等价 source→input→builder→artifact provenance，不复用 Windows
  路径/registry 作为供应链核心。

## [ADR-0064-DRIVERS] Decision Drivers

- 同版本号的不同 commit、dirty 状态或 payload 不得被当成同一构建。
- `-CheckSourceInputsOnly`、`-CheckInputsOnly` 与真实 ISCC build 必须使用不同成功文案，禁止 CI 冒充。
- 可执行文件要通过版本/能力探针，不能只因文件名存在就入包。
- manifest 必须自述它**没有证明什么**。
- 未签名策略与 provenance 是正交的；不能把 hash manifest 叫作签名。

## [ADR-0064-ALTERNATIVES] Alternatives

### [ADR-0064-ALT-A] A. 只在依赖文档里记版本和下载 URL

无法证明实际入包的是哪一个文件，也无法发现 frozen payload 被修改，拒绝。

### [ADR-0064-ALT-B] B. 对本地构建输入生成结构化 manifest 并 fail closed 校验

选定，部分实现。overlay 已把 source/recipe/vendor/frozen payload 复制到本轮 staging，对 staging 输入和
ISCC tree 持只读锁并在构建后复核，再原子发布带完成标记的最终单元；这比 point-in-time snapshot 更强。
它仍不等于上游真实性、hermetic/reproducible build 或已签名 attestation。

### [ADR-0064-ALT-C] C. 只接受签名上游、clean tagged commit，并生成最终 attestation

作为 release trust 目标。overlay 已配置真实构建 CI，但 clean/tagged policy、上游独立验证、签名密钥与
干净发布环境尚未实现，不得伪称正式 release trust 已成立。

## [ADR-0064-DECISION] Decision

### [ADR-0064-C01] Frozen backend manifest（overlay schema v3）

`backend/scripts/build_backend_exe.ps1` 必须在 frozen onedir 写入
`BUILD_PROVENANCE.json`：

- `artifact_type = ticketbox-frozen-backend`；
- backend version；
- 冻结前复制到本轮 input snapshot 的源码/构建配方路径、大小、SHA-256 和集合 fingerprint；
- 固定 Python、uv、PyInstaller 版本、来源合同、关键可执行文件 hash、lock hash、实际 installed
  distributions 与 Python execution tree；
- onedir payload（manifest 自身除外）的路径、大小、SHA-256、集合 fingerprint 与
  `ticketbox-backend.exe` 证据。

overlay 从 input snapshot 的 `.spec` 构建，构建期间对 snapshot/toolchain 持读锁并前后复核；只有 staged
payload 与 manifest 均通过才移动到最终 dist。installer 构建前再次计算当前 source 与 payload，漂移即
拒绝。该证据绑定本地执行输入，但仍不证明 Python/uv/PyInstaller 上游发布者真实性，也不宣称
PyInstaller 输出可复现。

### [ADR-0064-C02] Installer input manifest（overlay schema v3）

真实 ISCC build 生成 `artifact_type = ticketbox-windows-installer-inputs`，至少绑定：

- Git commit、dirty flag、status entry count 与 status fingerprint；
- Inno/PowerShell/release config 等 installer recipe 文件集 fingerprint；
- 已验证的 frozen backend v1 manifest、源码/payload fingerprint 与 EXE evidence；
- PostgreSQL bundle 的实际 payload fingerprint、关键文件、版本探针、license、
  `BUNDLE_MANIFEST.txt` 与其中记录的 source zip/URL/SHA-256；
- Shawl 实际 EXE 的 SHA-256、`--version`、`--help` 能力探针与版本策略；
- 固定 Inno archive 合同，以及被选中 `ISCC.exe` 的 engine/Product/File version、大小与 SHA-256；
- 实际传入 ISCC 的规范化 defines。

manifest 要作为 installer input 被嵌入安装目录，并与最终 EXE、`.sha256` 和 `BUILD_COMPLETE.json` 一起
形成精确四文件发布单元，以便事后验证本轮使用的本地输入和最终 artifact identity。

### [ADR-0064-C03] 三种构建模式不能混淆

| Mode | 可以证明 | 不能证明 |
| --- | --- | --- |
| `-CheckSourceInputsOnly` | 要求的 source/config 文件存在、release config 可解析并可计算 recipe/source fingerprint | `.iss/.isph`/PowerShell 语法、frozen dist、vendor、ISCC、安装器产物 |
| `-CheckInputsOnly` | frozen backend、PG、Shawl 本地输入通过验证 | ISCC identity、真实 installer provenance、最终 EXE |
| 真实 build | staged/locked inputs + ISCC identity + 构建后复核 + 最终 EXE hash/精确发布单元 | 上游真实性、clean/tagged policy、签名/可信时间戳、可复现性 |

CI job 名称和日志必须与该能力边界一致。overlay 的 GitHub/Gitea Windows lane 已配置 frozen backend
locked build、pinned vendor/toolchain preparation、真实 ISCC compile、`-VerifyOnly` 与 artifact upload；
这叫“workflow 已实现”，不是“云 CI 已产生成功证据”。`main@0f1092e625` 仍只有旧构建路径。

### [ADR-0064-C04] 版本 policy 与 exact evidence 并存

release config 可以用兼容范围拒绝明显不支持的 major/minor，例如当前 PostgreSQL `[17.10,18.0)`、
Shawl `[1.9.0,2.0.0)`；每一次实际构建仍必须记录**精确版本和精确文件 hash**。

兼容范围不是“任意版本自动可信”。vendor 更新必须同时经过依赖审计、官方来源核验、许可证检查、
行为探针、contract tests 和真实构建验证。

### [ADR-0064-C05] 当前 manifest 的信任边界必须明文

schema v3 固定声明：

```text
verification_scope = build-time-local-payload-integrity-only
upstream_authenticity_verified = false
```

因此：

- PG manifest 记录的 source URL/SHA-256 目前是本地声明，没有在构建时从独立官方渠道重新验证；
- Python/uv/Inno/PG/Shawl 的固定 URL、archive hash、payload hash 和版本探针证明“与仓库声明的合同
  一致”，不证明该合同最初来自真实发布者，也没有验证上游签名/透明日志；
- dirty worktree 当前允许构建，但 dirty 状态与 fingerprint 必须记录；
- overlay 已从冻结 source snapshot 执行 PyInstaller，也从 installer staging 执行 ISCC，并在构建后复核
  staging、toolchain 和 live input evidence；但 Windows 管理员/同主体恶意进程对目录或编译器的攻击
  抗性没有独立证明，不能称 hermetic sandbox；
- 最终 `Ticketbox-Setup-<version>.exe` 的 SHA-256 已写入 `.sha256` 与 `BUILD_COMPLETE.json`，并绑定
  provenance hash；这是本地完整性 publish receipt，不是签名 attestation；
- GitHub/Gitea workflow 的 real-build lane 只存在于未提交 overlay，尚无该 head 的云端成功 run；
- 没有可复现构建、透明日志、代码签名或可信时间戳。

任何文档、CI 名称或发布说明不得把这些边界升级成“上游真实性已证明”“构建可复现/完全 hermetic”
或“安装包已签名”。但也不得继续把 staged actual-input binding、固定 toolchain、真实 ISCC CI 配置和
最终 EXE hash 误列为完全未实现。

### [ADR-0064-C06] Actual-input binding 与正式发布门

overlay 已把 backend source/recipe、frozen payload、PG、Shawl 与 installer recipe 复制到本轮 staging，
从 staging 生成 manifest/产物，持读锁并做构建后 snapshot 复核；frozen manifest 也记录精确 Python、
uv、PyInstaller/toolchain evidence，installer 生成最终 EXE SHA-256 和原子四文件发布单元。该结构应保留，
任何不一致都删除本轮产物。

正式 release 仍必须增加：clean + annotated/signed tag policy；受控 runner identity；从独立官方渠道或
签名/透明日志验证上游；外置可验证 attestation（至少绑定 source commit、workflow、runner、输入
manifest、最终 hash）；代码签名/可信时间戳策略；干净 Windows VM 安装、升级、repair、卸载和数据保留
E2E。上述 gate 成立前，只能说“本地输入与 artifact receipt 可追溯”，不能说“可信正式发行”。

### [ADR-0064-C07] 代码签名策略与未签名支持矩阵保持独立

[[0047]] 当前仍选择默认不签。官方资料确认：新签名文件也可能因缺少 SmartScreen 文件信誉继续弹
提示；Smart App Control 在 enforcement 模式会阻止未知、未签名代码，签名全部装载二进制才是兼容
路径。是否引入 Azure Artifact Signing/传统证书/Store 分发是单独 release 决策，不由本 ADR 偷换。

无论签不签，provenance manifest 都继续存在；签名不能替代内部 payload 绑定，manifest 也不能替代
签名。

[[0047]] 原 Confirmation 中“未签名时一次『更多信息 → 仍要运行』”不是所有 Windows 策略的必然
路径，本 ADR 在该 scope 内替换为两类验收：

| Windows policy | Expected result |
| --- | --- |
| 允许用户 override 的 SmartScreen 环境 | 完成来源/hash 核验 walkthrough 后，可继续全链安装 |
| SAC enforcement 或企业策略禁止 override | 预期明确阻断并给出“不支持未签名安装/需签名发行”的结果；不得把不存在的“仍要运行”按钮当回归 |

## [ADR-0064-CALIBRATION] Current Implementation Calibration (dual baseline, 2026-07-11)

`implementation_status=partial` 反映 overlay 已完成 actual-input/publish receipt 的实质进展；
`verification_status=unverified` 是因为这些文件尚未提交、没有对应 cloud run，也没有 clean VM release
证据。不得把本地代码阅读升级成运行证明。

| Capability | `main@0f1092e625` | uncommitted installer overlay / evidence boundary |
| --- | --- | --- |
| frozen source/payload/EXE manifest | not implemented | schema-v3 manifest implemented locally |
| source staging + read locks + post-build revalidation | not implemented | implemented locally |
| pinned Python/uv/PyInstaller + hash-locked distributions | not implemented | implemented locally via toolchain contract/lock/evidence |
| Git commit/dirty/status fingerprint | not implemented | implemented locally；dirty build still allowed |
| pinned PG/Shawl archive + payload binding | PG zip hash only / partial | implemented as local evidence |
| pinned ISCC archive/compiler identity | PATH/machine discovery | implemented locally；exact engine/hash/defines recorded |
| immutable-ish installer staging + post-build revalidation | not implemented | implemented locally；未证明 hermetic/admin-adversary resistance |
| final installer hash + atomic publish receipt | not implemented | implemented locally：EXE、`.sha256`、provenance、completion 四文件精确集合 |
| explicit `upstream_authenticity_verified=false` | not implemented | implemented |
| frozen/vendor/real ISCC CI workflow | not implemented | GitHub/Gitea workflow configured；**no cloud run evidence yet** |
| clean/tagged commit release gate | not implemented | not implemented |
| independent upstream signature/authenticity verification | not implemented | not implemented |
| signed external build attestation / code signing | not implemented | not implemented |
| clean Windows install/upgrade/repair/uninstall E2E | not implemented | not implemented |

## [ADR-0064-CONSEQUENCES] Consequences

Good：检查时点的代码、配方、vendor 与 compiler 漂移会被结构化记录；旧 ADR 不再把已实现 manifest
误列为未来项；staging/lock/post-check 缩小实际读取 TOCTOU；CI 不能用 source preflight 冒充 installer
build。Bad：构建链和 manifest verifier 成为发布承重代码；发布者真实性、clean/tagged policy、外置
attestation、签名和 clean-machine E2E 仍需投入；允许 dirty build 只适合开发，不能自动成为正式
release policy。

## [ADR-0064-REVERSIBILITY] Reversibility, Replacement and Retirement

manifest schema 可版本化迁移，构建工具可替换；但不得回到“版本字符串/URL 即 provenance”或让 source-only
preflight 冒充 real build。工具替换必须双跑、比较 input graph/final hash，并保留旧 attestation verifier
直到所有受支持发布物退役。签名策略可独立改变，不得删除内部 payload binding。

复审触发：正式分发规模扩大、SAC/企业策略要求签名、vendor 停止维护/出现安全事件、构建需要跨机器或
remote builder、或 point-in-time TOCTOU 无法在 release lane 关闭。

## [ADR-0064-EVIDENCE] Verification and Evidence

- 改任一 tracked source、frozen payload 或 backend EXE：相应 manifest 验证失败。
- 在 PyInstaller/ISCC 读取期间替换输入：release build 必须因 staging 不可变或 post-build mismatch
  失败并删除产物；overlay 已有 staging/read-lock/post-check 路径，仍需 native kill/race 测试证明。
- 替换 PG/Shawl/ISCC 为同名不同 hash 或不满足版本/能力的文件：构建失败。
- `-CheckSourceInputsOnly` 日志明确“未验证 frozen/vendor/ISCC”；CI 不上传虚假 installer artifact。
- 真实 build 必须探测固定 ISCC identity，从 staging 编译，并在失败时删除本轮 publish unit；
  `-VerifyOnly` 必须复核精确四文件集合、最终 installer/provenance hash 和本轮 inputs。
- overlay workflow 必须先在对应提交的真实 GitHub/Gitea Windows runner 绿灯，上传的只能是通过
  `-VerifyOnly` 的精确 publish unit；本地 workflow 文本存在不是 CI evidence。
- 正式 release lane（未来）使用 clean/tagged commit，独立验证 vendor authenticity，生成外置签名
  attestation，并在干净 Windows VM 执行安装/升级/repair/卸载、保数恢复及两类未签名 policy 验收。

反向验收：同名不同 hash 输入仍能出包、ISCC 绕过 staging 读取 live tree、最终 EXE/manifest 没有独立
hash receipt、source-only CI 上传“安装器已验证”artifact，或 dirty/untagged artifact 被称为正式 release，
任一发生都证明 provenance 契约未成立。

## [ADR-0064-REFERENCES] References

- Shawl 官方仓库说明 ctrl-C、默认 3000 ms stop timeout、版本与 release：
  <https://github.com/mtkennerly/shawl>
- Inno Setup 官方 `ISCC.exe` CLI 与退出码：
  <https://jrsoftware.org/ishelp/topic_compilercmdline.htm>
- Microsoft SmartScreen reputation：新签名文件仍可能在积累信誉前显示提示：
  <https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation>
- Microsoft Smart App Control：enforcement 下未知未签名代码会被阻止：
  <https://learn.microsoft.com/windows/apps/develop/smart-app-control/overview>
- SLSA 对 provenance 的定义是可验证地追溯 artifact 在何时、何地、如何生成；本项目当前只达到其部分
  本地证据语义，不宣称 SLSA level：<https://slsa.dev/spec/v1.2/provenance>
