# 能力对账（后续审查不要重扫已固定 SHA 的链）

AUDIT_BASE = `c34efb40b89c4fecd85478888ed68ce84a90f10f`
审查对象 = `3d41f8f4afcdba89bd68b1f7dbb885e9b5ba063b`
CODE_HEAD = 见 `coverage.json`
状态：`INCOMPLETE`（审查回归 R01–R03 已关；U01–U06 已在现 Owner 内补；U07 本目录即交接入口）

完整扫描卡仍在 qualification-tools 证据根；本文件只记录**已固定结论**和**本轮返修**，避免重读已证实链。

## 已证实且本轮未重扫的链

| ID | 结论 | 源码锚点 | 不要重做的原因 |
|---|---|---|---|
| A01–A08 | PRESERVED | `pending_fx_task_service` / `ExpenseDao` / `publishAcceptedExpense` | 本轮未改核心 FX Writer |
| A09 Android | IMPROVED | admit → bindExact → enqueueExpenseBatch | 本轮只给期次 overload 加 reuse |
| A09 Web | MISSING | `/web/expenses/new` 仍 online-first | 禁止第二套 Outbox |
| A10–A12 | PRESERVED/IMPROVED | finishCompleted / resolve_payload_rate | 未改占用与债务汇率 |
| B01 | IMPROVED @ 3d41f8f4 | Editor selectCurrency；Web `#rc-add-currency` | 独立审查确认有效，禁止回退 |
| B03/B09/B11 | PRESERVED | 估值展示 / 共用 create / explicit link | 未改核心 link Owner |
| B07 | IMPROVED @ 3d41f8f4 | `createManualExpense(draft, binding)` | 本轮只在该 overload 复用已接纳原命令 |
| B05 | IMPROVED @ 3d41f8f4 | draft `return_*` + `draftHref` | 独立审查已跑 JS blob |
| #414 忙状态 | PRESERVED | 未整包覆盖 | |

独立审查若发现上表不成立，必须给出源码/执行反例后再改本表。

## 审查新增回归 → 本轮修复

| ID | 3d41f8f4 失败 | 现入口 | 能力 |
|---|---|---|---|
| R01 | 异常路径 `NameError: AppError` | `from app.errors import AppError`；422/409 保留原 key | FIXED |
| R02 | `null == null` 误选普通账单 | 无非空 clientRef 且无 accepted id 则不优先 | FIXED |
| R03 | reject 回期次无 Undo | GET 解析 undo + 模板表单；undo POST 回期次 | FIXED |

## U 项

| ID | 现入口 | 能力 | 限制 |
|---|---|---|---|
| U01 | `_payment_edit_href` / POST `payment_id` | IMPROVED | 无浏览器端到端 |
| U02 | `preferredPaymentAcceptedExpenseId` + outbox receipt | IMPROVED | 无 Room connected 刷新反例 |
| U03 | `_recurring_commitment_values` → `/new` | IMPROVED | 只预填商家/币种/金额，不改 hidden 本币 |
| U04 | `choosePeriodPaymentCurrency` | IMPROVED | 无 Compose 点击 |
| U05 | admitted 不重开；`reuseAdmittedLocalCreate` | IMPROVED | 假账本 VM + Fake DAO/Outbox |
| U06 | origin 草稿字段；restore 指定 clientRef | IMPROVED | `open()` 无 session 仍 current |
| U07 | 本目录 HANDOFF / RECONCILIATION / coverage.json | DELIVERED | 扫描卡正文仍在 qualification-tools |

## 剩余边（不要静默写成完成）

- A09 Web admission：Owner 决策
- C01 真机主旅程；C03 日用；C04 Gmail
- 全量 CI / 日用安装 / merge：分别授权
