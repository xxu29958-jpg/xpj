# 小票夹可执行架构契约标准

本标准定义 ADR 如何成为可执行工程约束。它不要求把每份历史 ADR 写成百科全书，也不把文档数量
当作架构质量。只有能减少歧义、阻止真实回归、降低迁移/恢复风险、明确责任或改善可替代性的条款，
才值得进入契约体系。

- Standard version: `2.3.0`
- Front matter schema: `2`
- Governing decision: [[0065]]
- Machine interface: `docs/current/adr-registry.json`
- Generated views: `docs/DECISIONS/README.md`, `docs/current/ADR_STATUS.md`,
  `docs/current/ADR_DEPENDENCY_GRAPH.md`

## 1. 裁决顺序

冲突时按以下顺序裁决：数据正确性 → 安全/隐私/权限隔离 → 可恢复性和数据主权 → 明确契约与长期
可维护性 → 兼容/迁移 → 稳定/可观测 → 性能/资源 → 用户操作体验 → 短期开发便利。

现行平台边界不变：PostgreSQL 是结构化业务数据唯一权威；Room 是可删除重建的客户端缓存；GUI、
Web 和移动端不承载权威业务规则；OCR/AI 只给建议；Windows 是首个宿主适配，不是领域核心。

## 2. 权威元数据与三类状态

### ACG-STATE-001 唯一来源

schema-v2 ADR 的 TOML front matter 是该 ADR 状态、责任、类型、风险和显式关系的唯一人工编辑来源。
`adr-registry.json` 是由 front matter 生成的唯一机器接口；索引、状态表和依赖图都是生成视图，禁止手改。

legacy ADR 是唯一例外：`legacy-baseline.json` 只冻结 path/ID/正文 SHA-256，
`legacy-calibration.json` 保存经实质审查后的当前状态、关系、责任和适用范围。两者合成 registry；
baseline 不能重签历史，calibration 不能改写历史正文，也不能在没有代码/拓扑 reason 时只为“全绿”降级决定。

### ACG-STATE-002 正交状态

- 决策状态：`proposed | accepted | rejected | deprecated | superseded`
- 实现状态：`not-started | implementing | partial | implemented | nonconformant`
- 验证状态：`unverified | verified | failed | stale`

三者不得互相代替。`accepted` 不等于已实现，`implemented` 不等于契约成立，`verified` 也不能掩盖
已被 supersede 的方向。实现进度和验证记录只更新 front matter/注册表及证据账本，不回写历史
Decision/Alternatives/Consequences。

### ACG-STATE-003 状态含义

- `nonconformant`：当前代码明确违反仍有效决策；不能用文档降低要求来消除。
- `failed`：最新有效证据证明关键条款失败。
- `stale`：曾有充分证据，但提交、环境、依赖、协议或时效触发器已变化。
- `verified`：所有适用关键条款达到本标准的“成立”证明，不只是找到相关文件。

## 3. ADR 类型、风险与字段强度

### ACG-TYPE-001 主类型

每份 ADR 选择一个主类型：`domain`、`data-consistency`、`security-identity`、
`deployment-runtime`、`client-interaction`、`performance-capacity`、
`dependency-technology`、`migration-retirement`、`governance-calibration`。

### ACG-RISK-001 风险级别

- `low`：局部、易回滚、无权威数据或信任边界影响。
- `standard`：跨模块但回滚清楚，失败域有限。
- `high`：涉及 schema/迁移、并发/事务/幂等、身份/密钥、跨端协议、公网、安装/备份/卸载或关键依赖。
- `critical`：失败可导致不可逆数据损失、恢复根失陷、跨账本/跨安全域泄漏或无法验证的发布物。

高/critical ADR 必须覆盖威胁或误操作主体、失败矩阵、迁移/回滚或明确不可逆性、故障演练入口、
独立复审和发布门禁。不适用项必须写具体 N/A 理由；“以后再说”不是 N/A。

### ACG-FIELD-001 强度

- `MUST`：缺失即 schema-v2 ADR 不合格。
- `SHOULD`：类型/风险适用时必须有；N/A 必须解释。
- `MAY`：有真实消费者或风险时再写。
- `N/A`：证明与该决策无关，不是留空。

## 4. 决策本体 MUST

每份 schema-v2 ADR 必须独立、明确地回答：

1. `Decision`：最终拍板的方案、边界和优先级；
2. `Alternatives`：至少两个真实可行方案及否决理由；
3. `Consequences`：收益、代价、限制和残余风险；
4. `Reversibility`：可直接撤销、需迁移、代价高或基本不可逆，以及替代/退役入口。

上下文、分析和实施草图不能代替这四项。目标能力必须标 `not-started/implementing/partial`，不得在
Decision 中用未来时态伪装为当前能力。

## 5. 稳定 clause ID

### ACG-CLAUSE-001 格式

schema-v2 的 H2/H3 关键条款使用 `ADR-NNNN-SUFFIX`。核心 MUST 固定为：
`SCOPE`、`ASSUMPTIONS`、`DRIVERS`、`ALTERNATIVES`、`DECISION`、`CONSEQUENCES`、
`REVERSIBILITY`、`EVIDENCE`、`REFERENCES`。决定内的可执行条款用 `C01`、`C02`……。

ID 一经发布不得复用、删除或改绑另一语义。accepted/rejected/deprecated/superseded ADR 的 summary、
current_scope、relations 和完整正文生成历史指纹；fenced code、Evidence、References、Errata 与 Calibration
同样属于历史。当前阶段没有正文可变区，后续证据走外部记录或新 ADR `amends/supersedes`。条款被替代时，
新 ADR 的关系与 scope 指向旧 clause，
旧 clause 保留历史。证据引用 clause ID，不引用易漂移行号作为唯一身份。

## 6. 前提、权威源与执行合同

### ACG-CONTRACT-001 前提与失效触发

ADR 必须列出当前拓扑、数据量/并发、网络信任、停机窗口、管理员权限、单机/单实例等前提，并给出
可观察的失效触发条件。不能用“通常不会并发”“用户不会这样操作”作为约束。

### ACG-CONTRACT-002 适用维度

按类型和风险裁剪以下维度：领域/数据/权限/事务/并发/安全/拓扑/交互/安装恢复不变量；对象生命周期；
权威源、缓存、投影和写入者；事务/OCC/幂等/committed-but-unseen；安全与隐私；凭证生命周期；性能/
容量/背压；可访问性和极端输入；故障域；部署/迁移/回滚/退役；可观测性/SLI/SLO；依赖/供应链；成本。

不要求每份 ADR 写完所有维度。高风险条款必须落到明确层：数据库约束、类型、服务边界、协议验证、
自动测试、CI gate、运行信号或故障演练。只有 prose 的条款只能处于 `unverified`。

## 7. 显式关系模型

允许：`depends-on`、`refines`、`amends`、`supersedes`、`conflicts-with`、`implements`、
`deprecates`、`informational`。每条关系必须有 target ADR 和 scope。

- `refines`：增加精度但不改变旧决定；`amends`：局部规范替换；`supersedes`：整体替代。
- `conflicts-with` 只能用于 proposed/deprecated 过渡；两个 accepted ADR 当前冲突是 merge blocker。
- 反向关系由注册表生成，不要求双写。
- 结构关系必须无环；当前消费者不得依赖已 superseded 决策而无替代说明。

## 8. legacy ratchet

### ACG-RATCHET-001 渐进迁移

- 新 ADR 必须 schema v2；
- 未触及 legacy ADR 可继续由 hash baseline 冻结；
- baseline 只包含 exact PR base 中真实存在的 legacy blob；不得选择本 PR 内 ancestor snapshot；
- baseline row（ID/path/hash）一经 bootstrap 不增、不减、不改；同 ID 原地 schema-v2 迁移禁止，方向变化
  新建 successor 并保留旧文件/row；
- legacy calibration 可独立更新，但每行必须绑定 reviewed-against commit、日期、reason；ID/path 必须存在于
  baseline，不能新增历史文件、改变 hash 或替代 successor ADR；
- schema/template 有版本；升级规则先兼容 N/N-1，再收紧，不能一次性让全仓历史爆红。

生成器对 legacy 文件做完整 SHA-256，并由 base-relative ratchet 阻止同一变更同时篡改正文和 baseline。
首次 bootstrap 还必须证明 baseline 正文 hash 直接来自 exact base commit。历史债务在后续切片按风险优先
用新 ADR 修订或 supersede，
不以批量模板填充冒充加固。

## 9. 证据分类、充分性和新鲜度

### ACG-EVIDENCE-001 证据类

- `STRUCTURE`：路径、symbol、依赖边、配置存在；只能证明有关联。
- `DB`：CHECK/UNIQUE/FK/transaction/lock 等数据库强制。
- `TEST`：自动正向、反向、并发或性质测试。
- `CI`：在真实构建/测试 lane 可重复执行的结果。
- `RUNTIME`：结构化日志、指标、审计事件、健康/版本信息。
- `DRILL`：断电、崩溃、备份恢复、迁移中断、故障注入。
- `MANUAL`：干净机、实机、辅助技术或真实网络拓扑验收。

### ACG-EVIDENCE-002 证明等级

- `linked`：至少一个 STRUCTURE 引用，只能说“有实现关联”。
- `covered`：适用层存在正/反测试或强制约束，并记录环境、命令、提交和结果。
- `established`：该 clause 的适用证据类全部有当前、可复现的 pass，且没有仍有效 failed 证据。

证据要求按 clause 风险裁剪，例如 data-high 通常需要 DB+TEST+CI，recovery-high 还需要 DRILL，deploy-critical
还需要 MANUAL。不得用 ADR 整体风险机械要求所有 clause 同一组证据；N/A 必须有具体理由和独立复审。
本标准只定义语义，不授权先造通用 proof-profile/receipt 引擎。出现稳定、重复的真实消费者后再独立决策自动化。

### ACG-EVIDENCE-003 记录字段

证据记录至少包含稳定 evidence ID、类别、结果、环境、命令、时间、source commit/artifact、验证 owner、
支持的 clause/reference 与失效条件。路径存在只能记 STRUCTURE，不能升级为 TEST/CI/DRILL。对应代码、环境、
依赖或时效变化后旧证据保留但标 stale；有效 fail 优先于旧 pass，恢复必须有后继提交/产物的新 pass。
accepted ADR 正文完整冻结，新证据不得覆盖其 Evidence 段；通用 ledger 落地前使用外部可追溯记录或后继 ADR。

当前切片没有通用 evidence ledger，因此高风险 ADR 不得标 `verified`；明确失败直接标 `failed`。未来引入
机器 evidence manifest 时必须小于其阻止的真实回归面、可替换，并由独立 ADR/测试验证，不能让工具自证。

## 10. mixed-version、协议和 schema 演进

跨端/数据库决策必须显式覆盖：新后端+旧客户端、旧后端+新客户端、schema 新于应用、离线客户端长期
重连、多实例版本偏差、字段新增/弃用/删除、最低客户端能力。默认顺序是：

```text
expand (新旧均可读写)
  -> migrate/backfill (可重入、可观察、可校验)
  -> capability/min-version gate
  -> contract (停止旧写入，再删除旧形态)
```

同一 API 稳定版本内不得把 rename 当无损变更；删除字段/enum/行为必须先有消费者证据和弃用窗口。
schema 已提升 `schema_min_compatible` 后，旧应用必须 fail closed，不能用数据库 restore/应用 rollback
把未知新事实当旧形态运行。详细矩阵见 `docs/architecture/PROTOCOL_EVOLUTION.md`。

## 11. 全系统权威源

`docs/architecture/AUTHORITY_SOURCE_REGISTER.md` 对结构化业务数据、图片/附件、凭证/恢复材料、安装配置、
客户端缓存、备份、日志审计和构建供应链分别登记在线权威、恢复副本、缓存、写入者、校验和损坏裁决。
“PostgreSQL 唯一业务权威”不等于图片 bytes、离线 outbox 或恢复材料可以被忽略；跨存储不一致必须有
显式 degraded 状态和修复/停止条件。

## 12. 治理工具的失败与升级

### ACG-TOOL-001 fail closed 的范围

front matter 解析失败、legacy hash 漂移、生成视图不一致、未知状态/关系、缺 target、结构关系环、两个
accepted 决策显式冲突，均为 merge blocker。PR/push/manual 必须给 exact pre-change base；本地无法解析
main/origin-main 或 HEAD parent 时同样失败，不允许跳过 ratchet 后打印完整 PASS。生成器只做本地确定性
解析，不联网、不修改 ADR 正文。

### ACG-TOOL-002 误报与例外

不得用代码内永久 allowlist 静默吞误报。若当前最小 gate 需要例外，只能精确记录
`(rule_id, subject, object_id)`、原因、risk owner、期限、跟踪项和残余检测；过期或不再命中必须失败。
schema 损坏、历史 hash 漂移和 accepted 决策正文改写不可豁免。工具 bug 优先修工具和回归测试。

### ACG-TOOL-003 CI/平台故障

本地确定性 gate 红必须修；CI 平台不可用不是代码绿，也不是契约失败。记录外部阻塞、保留本地完整
证据，待平台恢复后必须补云验证。不得因平台 502 改状态为 `verified` 或绕过发布门。

### ACG-TOOL-004 生成物和工具升级

机器生成区手改会被确定性重渲染检查发现。parser/generator 必须有 fixture、mutation 和仓库实况测试。
schema 升级使用 SemVer；先提供 N/N-1 fixture/双读或一次性迁移器并比较 registry/views，再收紧。
工具弃维时先双跑输出 diff。当前 gate 只解析 ADR/JSON/Git object，不联网、不重跑业务测试；相同 Git blob
只解析一次并设置性能预算。修改 verifier/schema 的变更不能用该变更自己的输出把自身标 established。

### ACG-TOOL-005 紧急修复

正在发生的数据损坏或安全暴露可先做最小 fail-closed 修复，但同一变更必须留下 incident/exception ID、
受影响不变量、验证和 owner；补 ADR/证据的到期日由 risk owner 明确。紧急通道不能用于普通赶工。

## 13. 责任、门禁与事故闭环

schema-v2 ADR 明确 Decision Owner、Implementation Owner、Verification Owner、Risk Owner。风险接受写明
范围和复审触发。问题分为：Release Blocker（数据/安全/恢复/供应链不可接受）、Merge Blocker（契约/
关键验证不完整）、Tracked Debt（有限且获批）、Observation（不阻断）。

事故闭环：事故/险情 → 根因 → 缺失/失效 clause → 修代码 → 补约束/测试/监控 → 新 ADR 或 amendment
→ 故障演练 → 证据归档。不得只修 symptom。

## 14. 什么不写 ADR

局部实现细节、易回滚重构、无跨模块/质量属性影响的命名、单个 bug 修复通常不写 ADR。用代码、测试、
注释或 runbook 即可。ADR 过大到同时拍板多个可独立替代方向时必须拆分；实施步骤过长移到 architecture/
runbook。没有真实消费者的未来接口、无法维护的指标、为填模板制造的状态机均禁止。

## 15. 人工与 AI 审计顺序

1. 先读真实代码、数据库约束、运行拓扑和冻结产品边界，确认系统现在是什么；
2. 逐份读 ADR 的 Decision/Alternatives/Consequences/Reversibility，找权限、权威、失败、迁移和扩展冲突；
3. 给出代码证据、影响和 retain/tighten/relax/split/revise/deprecate/supersede 的实质 disposition；
4. 仍有效不变量被代码破坏时标 nonconformant 并修实现；过时决定用 successor，不强迫代码倒退；
5. 实质决定稳定后再更新 calibration/front matter、关系、registry 和 clause ID；
6. 从 clause 追到 DB/TEST/CI/RUNTIME/DRILL/MANUAL，区分 linked/covered/established；
7. 只有重复、稳定且能阻止真实回归的证据流才自动化；治理成本超过收益时删除或收缩工具。

## References

- [AWS ADR process](https://docs.aws.amazon.com/prescriptive-guidance/latest/architectural-decision-records/adr-process.html)
- [Microsoft Well-Architected — Maintain an ADR](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record)
- [SEI — Quality attribute scenario elements](https://insights.sei.cmu.edu/documents/5465/2013_018_101_60984.pdf)
- [Google AIP-180 — Backwards compatibility](https://google.aip.dev/180)
- [Kubernetes API deprecation policy](https://kubernetes.io/docs/reference/using-api/deprecation-policy/)
- [OpenTelemetry observability primer](https://opentelemetry.io/docs/concepts/observability-primer/)
- [SLSA provenance](https://slsa.dev/spec/v1.2/provenance)
