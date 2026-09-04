# 小票夹文档导览

仓库施工先读根目录 [`AGENTS.md`](../AGENTS.md)。本页只是按责任找文档的索引，不是第二套规则，也不要求每个任务通读全部材料。

## 按责任进入

| 当前责任 | 入口 |
|---|---|
| 施工边界、验证、停止条件 | [`AGENTS.md`](../AGENTS.md)；需要细节时再读 [`rules/ENGINEERING_RULES.md`](rules/ENGINEERING_RULES.md) 对应章节 |
| 系统结构、API、身份、安全 | [`architecture/`](architecture/) |
| Windows 安装、服务、备份、恢复、排障 | [`runbook/`](runbook/)、[`../distribution/`](../distribution/)、[`../desktop/`](../desktop/) |
| 依赖、代码质量、错误文案 | [`rules/DEPENDENCIES.md`](rules/DEPENDENCIES.md)、[`rules/CODE_QUALITY_STANDARDS.md`](rules/CODE_QUALITY_STANDARDS.md)、[`rules/ERROR_MESSAGE_MAPPING.md`](rules/ERROR_MESSAGE_MAPPING.md) |
| 产品路线和设计参考 | [`roadmap/`](roadmap/)、[`design_reference/`](design_reference/) |
| 有日期/基线的审查与状态快照 | [`current/`](current/) |
| 查询某项长期决定为什么存在 | [`DECISIONS/README.md`](DECISIONS/README.md) |

## 渐进阅读

1. 先恢复用户当前 Goal、Owner 裁决、任务合同和 exact HEAD。
2. 沿真实调用链、目录和测试定位责任面。
3. 只读取会改变本次判断的架构章节、runbook、专题规则和 ADR。
4. 历史文档、旧 ADR、旧测试和旧工作流必须拿当前代码与运行事实复核。
5. 只有修改 ADR/治理工具本身时，才加载 [`rules/ADR_CONTRACT_STANDARD.md`](rules/ADR_CONTRACT_STANDARD.md)。

不要把“读过更多文档”当成正确性的替代品。一个局部任务通常不需要整本读取 `ARCHITECTURE.md`、`API.md`、全部 ADR 或整个规则目录。

## ADR 使用边界

ADR 保存长期决定及其理由，不是当前任务列表，也不自动证明实现已经符合。

- 先用 [`DECISIONS/README.md`](DECISIONS/README.md)、代码搜索或 [`current/adr-registry.json`](current/adr-registry.json) 定位相关决定。
- registry、状态表和依赖图只对其中标注的 review base 有效；基线早于当前 HEAD 时，它们只能作为检索线索。
- 选中 ADR 后读取正文，并与当前代码、迁移、测试和 active contract 交叉核对。
- 常规 bugfix、局部重构、样式、测试和既有决定的实现不需要新 ADR。
- 决策方向改变时写后继 ADR并声明关系；不要改写历史正文来伪造“当时已经实现”。

## 目录角色

- **rules/**：长期工程细则和专题标准。`AGENTS.md` 才是唯一默认施工入口。
- **architecture/**：当前跨模块契约；行为改变时与代码同步。
- **runbook/**：可执行操作步骤；必须说明前置、失败和恢复。
- **roadmap/**：未来计划与参考，不是当前施工授权。
- **current/**：带日期和基线的状态/审查产物；过期后不应继续作为默认入口。
- **DECISIONS/**：不可改写的决定历史及后继关系。
- **design_reference/**：设计资产和参考图。

## 版本

[`architecture/VERSION.md`](architecture/VERSION.md) 是版本号的权威入口；代码位置和发布状态必须由该文件列出的真实源核对。不要在本导览复制易过期进度叙事。
