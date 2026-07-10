+++
schema_version = 2
id = "NNNN"
title = "一句可裁决的标题"
summary = "一句话说明当前决定，不写实施愿望"
current_scope = "当前仍有效的最小范围"
date = "YYYY-MM-DD"
decision_status = "proposed"
implementation_status = "not-started"
verification_status = "unverified"
decision_type = "domain"
risk_level = "standard"
confidence = "medium"
decision_owner = "owner / 具体责任角色"
implementation_owner = "具体责任角色"
verification_owner = "不得与高风险实现 owner 完全同一视角的责任角色"
risk_owner = "接受残余风险的人"

# 仅在存在关系时添加；scope 必须具体到被继承/替换的条款。
# [[relations]]
# kind = "amends"
# target = "0000"
# scope = "ADR-0000-C02 的某一局部语义"
+++
# NNNN 决策标题

## [ADR-NNNN-SCOPE] Context, Scope and Non-goals

真实问题、适用模块/角色/客户端/部署形态、明确非目标。不要把实施计划当现状。

## [ADR-NNNN-ASSUMPTIONS] Assumptions and Applicability

当前拓扑、规模、网络信任、停机/管理员/单实例前提；每项写可验证失效触发。

## [ADR-NNNN-DRIVERS] Decision Drivers

- 按项目裁决顺序列真实驱动。
- 说明数据、安全、恢复、兼容、性能、体验和成本冲突时如何取舍。

## [ADR-NNNN-ALTERNATIVES] Alternatives

- **A. 真实可行方案**：收益、代价、否决理由。
- **B. 真实可行方案**：收益、代价、选择/否决理由。

## [ADR-NNNN-DECISION] Decision

一句话明确最终拍板。随后只写足以约束实现的条款。

### [ADR-NNNN-C01] 第一条核心不变量

写权威源、允许写入者、事务/失败边界和可执行结果；避免“合理”“尽量”“稳定”等不可证伪词。

### [ADR-NNNN-C02] 第二条核心不变量

按风险裁剪领域/数据/权限/并发/安全/隐私/凭证/性能/交互/拓扑/故障域/迁移/观测/供应链。
不适用时写 N/A 理由，不为填模板造抽象。

## [ADR-NNNN-CONSEQUENCES] Consequences

- Good：得到什么。
- Costs：开发、运维、用户、支持、CI、体积、认知成本。
- Limits / residual risk：明确接受什么，谁接受，何时复审。

## [ADR-NNNN-REVERSIBILITY] Reversibility, Replacement and Retirement

属于易撤销、可迁移、代价高还是基本不可逆；替代方案、触发指标、迁移/退役步骤和反向验收。

## [ADR-NNNN-EVIDENCE] Verification and Evidence

- 命令/测试/约束/故障演练；指出预期结果和失败时会看到什么。
- 为高风险 Cxx 选择适用证据类并映射到具体 symbol/constraint/test/CI/runbook；N/A 写理由和复审人。
- 证据记录稳定 ID、环境/命令、source commit/artifact、结果、时间/有效期、owner 与失效条件。当前没有
  通用 receipt 引擎；未闭环保持 unverified，明确失败直接写 failed/nonconformant。

## [ADR-NNNN-REFERENCES] References

- 相关 ADR clause、现行规则、官方一手资料。

## 类型与风险裁剪清单（复制前删除本节）

- `domain`：生命周期、权威事实、fold/派生值、权限、历史修正。
- `data-consistency`：transaction、lock/OCC、idempotency、partial failure、rebuild。
- `security-identity`：威胁主体、信任边界、凭证全生命周期、隐私、恢复/clone。
- `deployment-runtime`：平台适配、锁/回执、服务/进程/文件系统、升级/卸载、clean-machine drill。
- `client-interaction`：普通用户/owner/维护者操作边界、离线/弱网、重复点击、a11y/极端输入。
- `performance-capacity`：工作负载、响应度量、资源预算、背压/降级、测量命令。
- `dependency-technology`：来源、pin、license、维护/漏洞、hash/provenance、替代/退出成本。
- `migration-retirement`：expand→migrate→contract、混合版本、中断点、回滚/不可逆 gate、退役消费者。
- `governance-calibration`：权威范围、ratchet、工具失败/升级、误报/例外、CI 成本。
- `high/critical`：必须追加 threat/failure matrix、migration/rollback、observability、fault drill、独立复审和发布门；N/A 要有证明。
