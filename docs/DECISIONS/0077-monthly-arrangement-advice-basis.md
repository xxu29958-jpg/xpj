+++
schema_version = 2
id = "0077"
title = "月度安排与外部建议共享最小金额依据"
summary = "在既有匿名聚合中加入本次月度安排的五个金额，不发送事实身份、版本、历史或个人信息"
current_scope = "Internal Beta 月度安排、本地可安排金额、预算建议 provider 和 Web/Android 建议消费者"
date = "2026-09-27"
decision_status = "accepted"
implementation_status = "implementing"
verification_status = "unverified"
decision_type = "data-consistency"
risk_level = "high"
confidence = "high"
decision_owner = "当前 Goal 授权的 Codex 产品与架构主控"
implementation_owner = "Planning 后端及 Web/Android 消费者"
verification_owner = "当前片主控与既有 exact-head 门禁"
risk_owner = "项目维护者"

[[relations]]
kind = "amends"
target = "0036"
scope = "Current implementation note 的 provider 字段白名单，仅增加五个无个人信息的月度金额聚合"
+++
# 0077 月度安排与外部建议共享最小金额依据

## [ADR-0077-SCOPE] 范围

月度储蓄与备用金已有独立保存、显式试算和本地计算入口。外部建议必须看到本次计算采用的安排，
否则会把已经留出的金额再次分配。本决定只补齐最小建议依据，不改变 AI 仅建议、用户主动调用和本地事实权威。
ADR-0036 保留原文作为历史；当前阶段是 Owner Internal Beta，其历史文字中的 production 不表示已有生产履历。

## [ADR-0077-ASSUMPTIONS] 前提

字段名沿用既有 `_cents` 协议，值是 `home_currency` 对应的整数 minor units。保存币种与展示币种分离；
缺失换算或账务日期时不能拿零代替。储蓄与备用金是计划留出，不能解释成实际存款、账户余额或债务。

## [ADR-0077-DRIVERS] 原因

跨端读取、试算结果与 AI 解释需要指向同一次输入；未保存试算不能改写正式安排；已付款固定支出不能重复预留。

## [ADR-0077-ALTERNATIVES] 选择

- 保持旧 payload：拒绝，会让 AI 缺少用户已经确认或正在试算的预留金额。
- 发送安排记录与历史：拒绝，版本、身份、时间和修订明细不是解释可安排金额所需。
- 增加五个金额聚合并回传实际输入投影：采用，复用现有 provider、隐私 guard 和缓存责任。

## [ADR-0077-DECISION] 决定

### [ADR-0077-C01] 最小 provider 白名单

保留 ADR-0036 当前实现中的月份、币种、分类聚合、历史分位数、泛化收入计划和粗粒度固定支出摘要；
新增 `savings_target_cents`、`reserved_buffer_cents`、`outstanding_fixed_cents`、`discretionary_cents`、
`shortfall_cents`。新增字段只接受非负整数，由既有 outbound guard 拒绝自由文本或无效值。
商户、成员、备注、附件、token、账本身份、安排版本与历史均不进入 provider payload。

### [ADR-0077-C02] 单次计算依据与副作用

没有试算覆盖时读取已保存安排；显式试算必须同时提交两个预留金额及币种，并仅影响本次计算。
未履约固定支出用于剩余额度计算，不能再次扣除已关联付款的固定支出。缺失必要金额依据时阻止 AI 调用。
保存或刷新不触发 provider。建议响应附带实际采用的本地输入投影，消费者在编辑、换月、切换绑定或依据刷新后
不能把旧建议展示成新输入的结果；这份本地投影不意味着它的全部字段都可以外发。

## [ADR-0077-CONSEQUENCES] 后果

本地试算与 AI 解释保持一致，离线保存与非 AI 计算仍可独立使用。provider 多收到五个粗粒度金额；
外发仍不可撤回，因此继续保留主动调用、配置权限、匿名字段白名单和最小审计数据。

## [ADR-0077-REVERSIBILITY] 回退与退役

可以停用外部建议而保留月度安排及其历史。未来替换建议实现时必须迁移现有消费者与实际依据校验，
不得为回退删除保存事实、历史或未发送草稿；新增个人信息或更细粒度外发需要另行裁决。

## [ADR-0077-EVIDENCE] 验证

- 后端：`test_budget_inputs_projection.py`、`test_budget_advisor_aliases_and_guard.py`、
  `test_budget_advisor_openai_compat.py`、`test_budget_advise_endpoint.py` 覆盖投影、白名单和实际调用依据。
- 保存/试算：`test_monthly_arrangements_api.py`、`test_web_monthly_arrangement.py` 与
  Android `MonthlyArrangementRouteTest` 覆盖明确保存、保留原意图、试算不写事实及重开恢复。
- 此记录不宣称全片已验证；实际实现与原生运行资格以当前 PR 最终 SHA 的既有门禁为准。

## [ADR-0077-REFERENCES] 依据

- [[0036]] 原 AI 隐私边界；本 Goal 的完整产品目标与“有效能力只能加强”裁决。
- `backend/app/services/budget_advisor_service/` 与 `backend/app/services/monthly_arrangement_service.py` 的真实 Owner。
