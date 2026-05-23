# 0029 Use bill split invitations for cross-ledger bill splitting

- Status: accepted
- Date: 2026-05-23
- Decision makers: 项目维护者

## Context and Problem Statement

现有 `ExpenseSplit` 只表达同一账本内的分摊。V1.0 V10-02 需要支持 A 从个人账本发起拆账，B 在自己的账本记录支出。问题：如何在不破坏 [[0022]] "个人账本互不可见" 边界的前提下实现跨账本拆账？

业界主流（[Splitwise][splitwise-design]）的解法是 group-based 共享 expense view——但这跟 [[0022]] 隐私模型直接冲突，无法直接套用。

## Decision Drivers

- 个人账本互不可见（[[0022]]）；sender 与 receiver 都不得看到对方账本内部
- 接受后双方账单解耦：sender 后续改原账单不应影响 receiver
- receiver 不得看到 sender 的原 expense_id 或 sender ledger
- sender 不得知道 receiver 收进哪个个人账本
- accept 必须幂等（弱网 / 重发 / 双击不能生成两笔）
- 不复用 `ExpenseSplit` 承担工作流语义

## Considered Options

- Extend `ExpenseSplit` with `target_ledger_id`
- Add `cross_ledger_debt` as a side-product of expense
- Add `bill_split_invitation` workflow with explicit accept and decoupled receiver expense
- Adopt Splitwise-style shared group expense view

## Decision Outcome

Chosen option: **Add `bill_split_invitation` workflow**.

Sender creates an invitation addressed to `receiver_account_id`（不指定 receiver ledger）. Receiver accepts, choosing a target ledger where the receiver has write role; the backend then creates an independent confirmed expense in that ledger, copying snapshot fields only. After accept, sender's and receiver's expenses are fully decoupled.

Inbox is **account-scoped**, not ledger-scoped. Sender and receiver DTOs are separate so that sender-internal fields never leak in receiver responses and receiver ledger never leaks in sender responses.

不选 Splitwise group 模型：[Splitwise][splitwise-design] 的核心假设是"group 内全员可见同一笔 expense"，跟 [[0022]] 个人账本边界直接冲突；强行套用要么破坏隐私，要么退化成本 ADR 选定的 invitation 模型。

## Consequences

Good:

- `ExpenseSplit` 保持只服务同账本分摊语义
- 个人账本互不可见（[[0022]]）完整保留
- accepted 后 receiver expense 跟 sender 原 expense 解耦
- account-scoped inbox 让 receiver 切换 ledger 不影响邀请可见性

Bad:

- 引入新状态机（invited / accepted / rejected / cancelled / expired）
- sender 与 receiver 必须分两套 DTO，schema 不能复用
- reporting 必须谨慎处理 `source=bill_split_received`，避免未来家庭总览 double count
- 跟业界主流 Splitwise 模型不直接映射

## Confirmation

- DTO 泄漏测试：inbox response 不含 sender_ledger_id / sender_expense_id；sent response 不含 receiver_ledger_id
- account-scoped inbox 测试：receiver 切换当前 ledger 不影响邀请可见性
- accept 幂等测试：连续 accept 两次返回同一 received_expense_id
- viewer target rejection 测试：accept 到只读账本 → 403
- 链式拆账 rejection 测试：对已接受 expense 再 split-invite → 400
- received expense 不可改字段 guard 测试：amount / merchant / expense_time PATCH → 400
- 跨账本隔离测试：sender 改原 expense raw_text / image / 备注，receiver 端不变

## More Information

- [[0022]] Family Ledger Permission Model（本 ADR 是其边界**显式 account-scoped 例外**）
- [[0019]] 通知草稿模型（拆账邀请走同一 inbox）
- [[0021]] OCR 草稿字段来源（receiver 的 received expense 标 `source=bill_split_received`）
- [[0030]] 长任务（30 天 invitation expire 走 scheduler）
- [Splitwise — Designing Splitwise (data modelling)][splitwise-design]：业界 group-based 拆账参考；本 ADR 显式偏离

[splitwise-design]: https://medium.com/@riyag283/splitwise-an-lld-approach-c87e149af438
