+++
schema_version = 2
id = "0065"
title = "ADR 可执行架构契约与渐进式治理"
summary = "用 front matter、稳定 clause、base-relative ratchet、派生证据和生成 registry 把 ADR 变成可验证契约"
current_scope = "ADR 元数据、生成视图、历史/校准分离、稳定 clause 与最小 ratchet；证据自动化延后"
date = "2026-07-11"
decision_status = "accepted"
implementation_status = "partial"
verification_status = "unverified"
decision_type = "governance-calibration"
risk_level = "high"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "架构治理维护者"
verification_owner = "独立 review + CI"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "supersedes"
target = "0056"
scope = "双状态模型、人工状态账本、新 ADR 质量门和机器守护机制；历史真实性原则继续保留"
+++
# 0065 ADR 可执行架构契约与渐进式治理

## [ADR-0065-SCOPE] Context, Scope and Non-goals

[[0056]] 已经正确建立“历史决定不可改写、实施状态单独维护、lineage 机器检查”的基础，但仍有三个
结构缺口：Markdown 状态表同时承担人读和机器权威；决策/实现/验证没有完全分离；新 ADR 只有通用
MADR anatomy，没有稳定条款 ID、风险裁剪、证据充分性和 legacy ratchet。

结果是 0047 的 accepted/partial、0048 的 rejected、0039 的历史快照和若干“target contract 已落地”
容易在索引/正文/代码间漂移。若直接强制所有旧 ADR 套新模板，又会让全仓爆红或诱导批量灌水。

本 ADR 只决定治理机制和首批架构目录。它不一次性重写旧 Decision，不用生成器判断业务实现真假，
也不为 Linux/多机/云端创建没有消费者的接口。

## [ADR-0065-ASSUMPTIONS] Assumptions and Applicability

- 仓库以 Git 保存决策史，CI 能运行 Python 3.11+；因此 TOML 可由 stdlib `tomllib` 解析，无需新依赖。
- 当前 0001–0061 存在大量异构格式，不能在一个 PR 内可靠补齐全部决策本体。
- 状态、关系、索引和 graph 可机器确定；“契约是否真的成立”必须依赖代码/DB/测试/运行证据，不能由
  linter 猜。
- 若 registry gate 显著拖慢 CI、产生不可解释误报，或 schema 变更必须手工同步多份来源，则本方案
  失效并触发复审。

## [ADR-0065-DRIVERS] Decision Drivers

- 数据、安全和恢复条款必须可证伪，未实现目标不能冒充完成。
- 决策史不可伪造，但旧决定不能拖当前明确方向倒退。
- 新债必须立即禁止；旧债按风险 ratchet，不能一次性阻塞仓库。
- 人工和 AI 必须从同一机器接口得到基本一致的状态、关系、责任和 clause identity。
- 治理工具本身要有测试、升级/误报/CI 故障/紧急修复协议，不能成为第二套上帝系统。
- 不为“完整”无限加章节；硬件补齐后转向代码、约束、测试、CI 和故障演练。

## [ADR-0065-ALTERNATIVES] Alternatives

- **A. 继续以 Markdown README/ADR_STATUS 为人工权威。** 否：解析脆弱、状态混合、生成视图可漂移。
- **B. 立即把全部历史 ADR 重写成统一模板。** 否：伪造历史、审阅面过大、会制造无意义 N/A 和假证据。
- **C. schema-v2 front matter + 生成 registry/views + legacy history/calibration ratchet。** 选择：新 ADR 严格，
  旧正文不动不爆红，当前符合性可校准，发生正文修改时渐进迁移。
- **D. 引入外部 ADR SaaS/数据库。** 否：破坏离线仓库可审计性，新增依赖/权限/导出风险，收益不足。

## [ADR-0065-DECISION] Decision

选择 C，并将 [ADR_CONTRACT_STANDARD](../rules/ADR_CONTRACT_STANDARD.md) `2.3.0` 作为规范正文。

### [ADR-0065-C01] 三状态和权威来源分离

schema-v2 front matter 是该 ADR 的状态/关系/责任来源；legacy 使用正文/hash baseline + 独立 calibration overlay。
两者生成 `adr-registry.json` 这一唯一机器查询接口，README、状态表、依赖图只作确定性可再生视图。
Registry 不产生领域决定；决策、实现、验证使用三个正交枚举。

实现进度、验证状态和新证据只更新 metadata/证据账本；原 Decision/Alternatives/Consequences 不回写成
“当时就完全正确”。方向改变写 refines/amends/supersedes ADR。

### [ADR-0065-C02] 决策本体和稳定条款是 MUST

新 ADR 必须独立列 Decision、Alternatives、Consequences、Reversibility，并使用
`ADR-NNNN-SUFFIX/Cxx` 稳定 ID。行号只能帮助 review，不能作为证据唯一身份。ID 发布后不复用。

### [ADR-0065-C03] legacy 历史与当前校准分离

exact PR base 中既存 legacy ADR 的 path、ID 和正文 SHA-256 由 baseline 冻结；当前状态、关系、责任和
适用范围由独立 calibration overlay 表达。bootstrap 不得选择本 PR 内 ancestor snapshot；baseline row
此后不增、不减、不重签。同 ID 原地 v2 迁移无法证明历史未被改写，因此禁止；方向变化写新 successor。

calibration 的组合审查日期、代码基线和范围位于 calibration root。条款变化必须记录新 reason、真实且为
HEAD 祖先的新 reviewed-against commit，以及非倒退、非未来日期。accepted/rejected/deprecated/superseded
schema-v2 的 summary、current_scope、relations 和完整正文历史指纹包含 fenced code、Evidence、References、
Errata 与 Calibration；当前阶段没有正文可变区，语义或证据变化走 amendment/supersession 或外部证据记录。

### [ADR-0065-C04] verified 需要“成立”证据

STRUCTURE 只证明关联；DB/TEST/CI/RUNTIME/DRILL/MANUAL 按风险闭环后，才能从 linked→covered→established。
本切片只定义证据语义，不实现通用 receipt/drill 引擎，也不把路径清单包装成证明。真实消费者和稳定契约出现后，
再以独立切片实现最小证据 manifest。此前 schema-v2/legacy 的高风险决定不得标 `verified`；代码证据明确失败时
直接标 `failed/nonconformant`，不能等待工具。

### [ADR-0065-C05] mixed-version、authority 和 invariant 只作审查目录

`PROTOCOL_EVOLUTION.md`、`AUTHORITY_SOURCE_REGISTER.md` 与 `CORE_INVARIANTS.md` 汇总已审定 ADR 和代码证据，
帮助发现遗漏；它们不是决策源、业务真源或独立规范。目录条目只有能追到 accepted ADR/代码约束时才可标当前成立；
冲突必须先由实质审查和新 ADR 裁决，再更新目录，禁止反过来用目录生成架构。

### [ADR-0065-C06] 关系图和冲突必须机器检查

显式关系限定为 depends-on/refines/amends/supersedes/conflicts-with/implements/deprecates/informational，
每条有 scope；target 必须存在，结构关系无环。两个 accepted 决策显式冲突是 merge blocker。

### [ADR-0065-C07] 治理工具有自己的恢复协议

parser/generator 本地确定、只读验证；显式 render 才改生成视图。当前 gate 只检查 schema、baseline、
calibration、关系、accepted history 和 stale view，不联网、不重跑业务测试、不判断实现真假。工具入口必须进入
版本控制并由 clean clone 发现。PR 使用 exact target SHA，push 使用 pre-push SHA，manual run 显式给 base；
本地无法解析 main/origin-main 或 HEAD parent 时失败，禁止 `SKIP + PASS`。平台 502 只标外部阻塞，不能改绿/
verified。误报先修工具和回归测试；需要临时
例外时用限时、精确的 rule/subject/object 记录。紧急数据/安全修复可先 fail closed，但要登记补契约期限。

### [ADR-0065-C08] 按可合并切片演进

切片顺序固定为：真实代码/运行拓扑/冻结产品边界 → 逐份实质 disposition → 必要 amendment/supersession →
最小 metadata/registry/clause/ratchet → 代码/约束/测试 → 有真实消费者后再加 evidence/CI/drill automation。
治理工具只能固化已经确认的决定。每片独立验证/复审/PR；任何工具规模超过它所阻止的真实回归时立即收缩。

## [ADR-0065-CONSEQUENCES] Consequences

- Good：状态漂移、生成区手改、legacy/accepted 历史偷改、未知关系/环/accepted 冲突在 CI 可见；条款可以稳定映射证据。
- Good：旧 ADR 不需要批量重写，当前代码方向可用 amendment 收口，历史仍可追溯。
- Costs：增加小型 parser/generator、历史 baseline、calibration overlay、JSON registry 和生成视图。
- Limits：当前机器只证明结构、历史身份和生成一致性，不判断业务 claim 已成立；证据自动化/故障演练后置。
- Residual risk：calibration 仍是人工架构判断，必须引用代码/拓扑证据；hash 通过只证明历史未改写。

## [ADR-0065-REVERSIBILITY] Reversibility, Replacement and Retirement

TOML/JSON/生成器实现可迁移，代价中等；三状态分离、稳定 clause、legacy ratchet 和证据充分性原则不可
回退。替换工具必须先双跑同一 corpus、比较 registry/views、证明无 baseline/关系/状态丢失，再由新 ADR
supersede。若 gate 持续超时/误报、schema 无法 N/N-1 演进或生成物经常需要手修，视为方案失效。

## [ADR-0065-EVIDENCE] Verification and Evidence

- `python backend/scripts/_audit_adr_contracts.py`：front matter、可见区、base ratchet、历史指纹、关系、registry 和 views 全绿。
- `python backend/scripts/render_adr_contract_views.py` 后 `git diff --exit-code`：生成确定、无隐藏漂移。
- pytest mutation 覆盖 fence/comment 伪条款、fenced wire contract、summary/scope/relations、Cxx 归属、
  exact-base bootstrap、baseline 重签/删除/同 ID v2 重写、calibration 假 commit/倒退日期/状态复活、
  locked 正文改写、关系缺 target/cycle、accepted conflict 和生成视图手改。
- 全量 `release_audit.py` 必须自动发现本 lane；云 CI 绿之前 verification_status 保持 unverified。
- 独立对抗 review 检查过度治理、历史伪造、parser 绕过、状态自相矛盾和“工具替代架构判断”。

## [ADR-0065-REFERENCES] References

- [[0056]] ADR 生命周期与当前状态账本（本 ADR 在其基础上收紧）。
- [AWS Prescriptive Guidance — ADR process](https://docs.aws.amazon.com/prescriptive-guidance/latest/architectural-decision-records/adr-process.html)
- [Microsoft Well-Architected — Maintain an ADR](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record)
- [SEI — Quality Attribute Scenarios](https://insights.sei.cmu.edu/documents/5465/2013_018_101_60984.pdf)
