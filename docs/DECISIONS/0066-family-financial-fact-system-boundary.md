+++
schema_version = 2
id = "0066"
title = "小票夹作为家庭账务事实系统的领域与适配边界"
summary = "以家庭账务事实、身份和多端协作为核心，替代早期小票上传器产品边界"
current_scope = "领域核心、八个承重域、当前 Windows 单机拓扑与未来宿主/客户端扩展缝"
date = "2026-07-11"
decision_status = "accepted"
implementation_status = "partial"
verification_status = "unverified"
decision_type = "domain"
risk_level = "high"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "领域、后端、客户端与宿主 adapter 维护者"
verification_owner = "独立 domain/security/recovery reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "supersedes"
target = "0017"
scope = "早期灰度上传工具的产品范围、角色和人工确认入口叙述"

[[relations]]
kind = "refines"
target = "0024"
scope = "member、owner、维护者和审计者的跨端交互边界"

[[relations]]
kind = "refines"
target = "0041"
scope = "PostgreSQL 权威与 Windows/PostgreSQL adapter 的领域隔离"
+++
# 0066 小票夹作为家庭账务事实系统的领域与适配边界

## [ADR-0066-SCOPE] Context, Scope and Non-goals

[[0017]] 形成时，小票夹的主流程仍是“手机上传截图 → Windows 保存/OCR → Android 人工确认”。当前代码已经
拥有 Account/Ledger/Member/Device、公开 Web session、owner console、预算、债务、家庭分账、回收站、商家与
规则、后台任务、离线 outbox、报表和恢复工具。继续按“小票上传工具”裁决，会把 Android 误写成唯一人工入口，
把 `/web` 误写成本机页面，把 Windows/SCM 误写成领域核心，并让账本、家庭身份和财务事实缺少共同边界。

本 ADR 只决定小票夹**是什么、哪些域承重、核心和 adapter 如何分开**。它不把未来 Linux、云端、多实例或
新客户端预先实现，也不替代金额、身份、同步、图片、AI、迁移和安装 ADR 的细节。

## [ADR-0066-ASSUMPTIONS] Assumptions and Applicability

- 当前部署是一套 PostgreSQL、一个 active backend writer、Windows 宿主和多个可能长期离线的客户端。
- 使用者是一个家庭或私有协作组；owner 可以维护账本，但不因此自动获得恢复材料或宿主管理员权限。
- 数据正确性、安全、隐私和可恢复性优先于界面便利或短期实现成本。
- 自动化可以失败或被关闭，人工账务路径仍应工作；服务端不可用时客户端可保存明确的未提交意图。
- 多机器/多 active writer 当前不受支持；未来若进入真实路线，必须新增版本偏差、迁移 ownership 和一致性 ADR。

## [ADR-0066-DRIVERS] Decision Drivers

- 当前领域已经远超上传、OCR 和 pending 列表，旧边界会直接造成权限、恢复和同步错误。
- 账务事实必须有单一裁决源，缓存、图片 bytes、恢复副本和未提交意图又不能被一个“数据库真源”口号抹平。
- 家庭 member、ledger owner、设备、Web session、UploadLink、维护者和恢复主体必须最小授权。
- Windows 是首个受支持宿主，但 Linux/云端 adapter 不应迫使金额、身份、账本或人工确认模型重写。
- 新能力必须从明确扩展缝进入，不能靠配置袋、固定路径或“通常只有一个进程”维持正确性。

## [ADR-0066-ALTERNATIVES] Alternatives

### [ADR-0066-ALT-A] A. 继续以截图上传和 Android 确认为产品核心

拒绝。它与现有 Web、家庭身份、预算、债务、分账、多端写入和恢复代码冲突，会让真实承重能力处于无契约状态。

### [ADR-0066-ALT-B] B. 把小票夹定义为通用财务/云平台

拒绝。它会提前引入多租户商业注册、分布式共识、任意货币/会计准则和云运维复杂度，没有当前消费者。

### [ADR-0066-ALT-C] C. 家庭账务事实核心 + 可替换宿主/客户端/provider adapter

选定。核心只承载已经存在或已冻结的家庭账务、不变量和协议；部署、UI、OCR provider 与存储实现通过窄边界适配。

## [ADR-0066-DECISION] Decision

### [ADR-0066-C01] 产品核心是家庭账务事实，不是上传媒介

小票、手工录入、通知解析、CSV、家庭分账和未来受控导入只是事实入口。系统核心是：在账本和家庭身份范围内，
形成可追踪、可确认、可撤销/补偿、可同步、可恢复的财务事实与只读投影。入口类型不得改变金额、权限、OCC、
幂等、审计和人工确认规则。

### [ADR-0066-C02] 八个承重域必须有明确 owner

| 承重域 | 核心责任 | 禁止下沉/上移 |
| --- | --- | --- |
| 宿主机生命周期 | 启停、进程身份、数据目录、资源和 adapter 健康 | 不定义账务状态或家庭权限 |
| 账本权威 | 结构化事实、引用、权限、状态机、投影重建 | 不信任 Room/UI/文件名成为真源 |
| 家庭身份 | account/ledger/member/device/session/capability/recovery 分离 | 不以 loopback、owner UI 或管理员账户替代授权 |
| 多端写入 | 同一服务端命令、权限、OCC、幂等与结果 envelope | Screen/Web JS 不复制权威状态转换 |
| 离线冲突 | 本地 intent、binding、payload version、重放和显式冲突 | 不把未提交 intent 当 server fact 或普通 cache |
| 财务事实 | 金额、货币、时间、债务、分账、调整和补偿 | 不用 float、显示字符串或可变投影裁决余额 |
| 图片与 AI 建议 | 受保护证据、provenance、最小外发和建议 ownership | 不让 OCR/AI 自动确认或覆盖用户事实 |
| 安装升级与恢复 | schema、程序、配置、bytes、凭证的迁移/回滚/恢复 | 不把文件存在、health=ok 或 pg_dump 单项当恢复成功 |

### [ADR-0066-C03] 权威、证据、意图和缓存是四种不同身份

- PostgreSQL 是结构化账务事实、权限、状态机和引用关系的唯一在线权威。
- 规范化收据 bytes 是独立受保护证据；PG 保存引用/hash/状态，不能从一行记录重建 bytes。
- Room outbox 是该设备尚未被服务端确认的持久意图；成功后 PostgreSQL 结果胜出。
- Room confirmed 行、Web view model、报表和缩略图是可删除重建的投影。
- 备份只是候选恢复副本；只有通过同代 schema、身份、财务汇总和二进制清单校验后才能晋升。

### [ADR-0066-C04] 自动化只建议，人工命令才改变权威事实

OCR、AI advisor、规则候选和重复检测可以写 provenance 完整的建议或 preview。它们不得自动确认账单、修改已确认
字段、写预算真相、绕过权限/OCC，provider 故障不得阻断手工记账。用户已修改字段必须脱离自动 ownership；重新
识别不得覆盖已确认事实。规则批量应用等明确用户命令仍可写入，但必须展示范围、结果、失败和撤销/补偿边界。

### [ADR-0066-C05] 角色与界面按能力分面，不按技术信息一刀切

- member 处理被授权账本的日常事实和个人设备/会话；不能管理恢复材料或宿主。
- ledger owner 管成员、账本策略、邀请和 owner transfer；不自动获得 OS/数据库恢复权限。
- maintainer 管宿主、安装、备份和诊断；不能因本机管理员身份绕过应用审计去执行普通业务命令。
- recovery operator 只在受控 ceremony 中接触密封恢复材料，并与日常服务账户隔离。
- auditor 读取允许的业务审计和脱敏运行证据，不获得写权限。

服务器地址可以在需要连接、诊断或解释作用域时展示；token、路径秘密、恢复材料、数据库连接和 provider payload
不得因“高级界面”而暴露。普通失败界面必须说明副作用、重试安全性、数据是否仍在和下一步。

### [ADR-0066-C06] 当前拓扑是部署条件，不是永久领域约束

当前 Windows adapter 可以使用 Inno、SCM、PowerShell、ProgramData、loopback 和虚拟服务账户。领域模型、后端
service 接口和客户端协议不得依赖注册表、固定端口/域名/路径、GUI 进程或单一文件系统。未来 Linux/云端新增
adapter；未来多实例必须先解决 migration ownership、version skew、后台任务 claim 和单 writer 假设，不能直接
打开第二个 writer。

### [ADR-0066-C07] 失败隔离不得静默改变业务语义

OCR/provider、单个账本任务、图片缺失、客户端离线、GUI 崩溃和安装器失败应落在各自 fault domain。允许暂停建议、
排队 intent、降级只读或进入 repair；禁止静默 1:1 FX、清空 outbox、自动确认、把缺图写成已清理、让旧 binary 对
未知 schema 继续写，或用 health response 宣称数据已恢复。

### [ADR-0066-C08] 扩展必须有真实消费者和退出条件

新增客户端、provider、存储或宿主只实现 adapter 与 capability；修改核心不变量必须新 ADR。没有当前消费者的
多云抽象、插件总线、通用会计引擎和多 active writer 不进入主线。每个 adapter 必须记录支持矩阵、资源预算、
失败/替代条件和退役路径。

## [ADR-0066-CONSEQUENCES] Consequences

Good：旧上传器边界不再拖住家庭身份、账本、Web、债务、预算和多端演进；Windows 与 provider 细节被限制在 adapter；
权威、图片、意图、缓存和恢复副本不再混称“数据”。Costs：现有若干 ADR、架构总览和实现状态必须校准；部分看似
方便的 public admin、outbox 清理和配置回落会变成显式红灯。Limits：本 ADR 不自动实现 Linux/云端/多实例，也不
证明任何具体恢复流程已成立。

## [ADR-0066-REVERSIBILITY] Reversibility, Replacement and Retirement

把产品退回纯上传工具在数据/身份迁移上代价高且不符合现有消费者；领域边界原则长期保留。Windows、Android、Web、
provider、文件存储和任务 executor 可逐项替换，前提是新 adapter 通过同一领域/协议验收。若未来成为商业多租户或
受监管会计系统，本 ADR 必须被新的 tenant isolation、审计保留、会计政策和运维责任模型 supersede；不能靠不断
扩写本 ADR 假装适用。

## [ADR-0066-EVIDENCE] Verification and Evidence

- 后端模型/路由消费者清单证明 Account/Ledger/Member/Device、Expense/Budget/Debt/Split、Web/Owner、tasks、
  recycle、OCR/AI 均已存在，早期上传器描述不完整。
- 结构化事实写入只经后端 auth/permission/service/transaction；Android Screen/ViewModel 和 Web JS 不直接写 DB。
- 删除 Room confirmed cache 后可从 PG 重建；保留 outbox 时未提交 intent 不丢失。当前 v10 migration/logout 不能通过，
  因此实现状态保持 partial。
- 关闭 OCR/AI provider 后，手工创建/编辑/确认仍可完成；并发用户修改/确认阻止后台 enrichment 覆盖。
- Windows adapter 替换测试使用不同路径/端口/服务名时领域测试不变；多实例 writer 当前启动门必须明确拒绝。
- 故障矩阵覆盖图片缺失、provider timeout、outbox unknown version、旧 client、DB migration 中断和 installer repair。

反向验收：任一客户端缓存可覆盖更新的 PG 事实、自动化能确认账单、服务地址/SCM 进入领域类型、清 cache 会删未提交
intent、或数据库备份成功被等同为图片/凭证完整恢复，都证明本领域边界尚未成立。

## [ADR-0066-REFERENCES] References

- [[0041]] PostgreSQL 权威与迁移方向。
- [[0042]] 离线意图、OCC 与幂等边界。
- [[0049]] 家庭债务领域与成员权限。
- [[0059]] 恢复/clone 身份边界。
- [[0061]] home currency minor-unit 语义。
- [Microsoft Well-Architected — Architecture decision records](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record)
