# TBX-404-405-RECONCILE 交接入口

状态：`INCOMPLETE`（R01–R03 与 U01–U06 已在本分支返修并有直接执行证据；不是 #404/#405 全范围完成，不要按完整交付合并）
任务：完整核对 #404/#405 及后续承接。允许结束态仍是 INCOMPLETE / SCAN_COMPLETE_*。

## SHA

- 仓库：`xxu29958-jpg/xpj`
- 分支：`cursor/tbx-404-405-reconcile-20260915`
- 审查对象（返修输入）：`3d41f8f4afcdba89bd68b1f7dbb885e9b5ba063b`
- 直接父提交 / 当时 main：`c34efb40b89c4fecd85478888ed68ce84a90f10f`
- #405 对照（非金标准）：`c0279d865dca15bb1ac1786d66c1119ed0448db6`
- #415（仅 B01 币种入口）：`14c9eca8cf6a301a6f0d9c7a7c8dfb0227c424b9`
- #404 merge：`a6ebf182a753b5c0ea881a3913a39459a3e10041`
- 本交接对应 CODE_HEAD：见同目录 `coverage.json` 的 `code_head`（提交后回填）

施工面：`E:\projects\xiaopiaojia-404-405-reconcile`
详细扫描卡（不在本 git 树）：`E:\projects\ticketbox-qualification-tools\tbx-404-405-reconcile-20260915\evidence\`
文件归属：同目录外 `inventory/file-attribution.tsv`（UNMAPPED=0）。勿用 `evidence/scan-A.md` 的错误 ID 映射。

未 merge、未装日用、未改用户数据、未调用 Codex。

## 不要整体回退的已确认正向改动（3d41f8f4）

| 能力 | 入口 | 不要回退的原因 |
|---|---|---|
| B01 两端外币创建 | Android `RecurringEditor` `selectCurrency`；Web `#rc-add-currency` | 已有 JVM/Web GET→POST→DB 证据 |
| B07 bindExact | `createManualExpense(draft, submitted.binding)` → `bindExact` | 只修期次付款入队接缝 |
| B05 Web 草稿来源 | `manual-drafts.js` `return_*` + `draftHref()` | 原 JS blob 四项保留 |
| B10 返回焦点 | `return_payment_expense_id` → `payment_id`；`preferredPaymentClientRef` | 焦点卡存在；本轮补了核对回程 |

## 本轮关闭的审查回归

| ID | 生产入口 | 直接反例 |
|---|---|---|
| R01 | `web_recurring_occurrences.py` 恢复 `AppError` import | `test_web_association_invalid_action_keeps_the_original_key`（422+原 key）；`test_web_association_state_conflict_keeps_the_original_proposal`（409+原提案） |
| R02 | `preferredOccurrencePaymentId` 无非空身份不启用优先 | `RecurringOccurrencePaymentPickerTest`：null/null、月份/搜索不匹配为空；明确 accepted id / clientRef 才置顶 |
| R03 | 期次页渲染 undo；`web_expense_undo` 带回原期次 | `test_web_reject_from_recurring_occurrence_returns_to_the_original_period`：真实 series、follow GET、可见撤销、POST undo 回期次且行回 pending |

## U01–U06 本轮入口（不要把接线当完成）

| ID | 做了什么 | 执行证据 | 仍不是什么 |
|---|---|---|---|
| U01 | 焦点/列表/已关联「核对」走 `flow_href`+origin；POST 失败保留 `payment_id` | `test_focused_payment_review_keeps_the_original_period_return`：GET 焦点卡 → edit 含 return_* → 再回期次仍有焦点卡 | 未跑浏览器 BFCache |
| U02 | 优先付款先用 `acceptedExpenseId`，再非空 clientRef | picker 测 + session `acceptedExpenseId`；确认流动态回填 | 未跑真实 Room 刷新抹掉 clientRef 的 connected 测 |
| U03 | `/web/expenses/new` 从原 series 预填商家/币种/金额；不改 hidden 本币 | FX 旅程 GET `/new` 断言 `海外订阅` / `20.00` / `USD` selected，随后仍按原 USD 创建 pending | 不是 Android initials 的替代声明 |
| U04 | 未知义务币种打开选择，不猜 CNY | Host `PeriodPaymentCurrencyChoice`；Surface 仍禁止 `?: CurrencyCode.CNY` | 未跑 Compose 点击 |
| U05 | admitted 不再重开创建；`bindExact` 复用已接纳 local create | VM `admittedPeriodPaymentReentryPinsPreferredAndDoesNotReopenCreate`；`ExpenseManualCreateOfflineTest` 第二次 exact-binding 不新增 outbox | 未宣称服务端去重已重跑 |
| U06 | origin 增 merchant/amountText/expenseTime；restore 按指定 clientRef | session 单测双任务只恢复第一个 clientRef/71 | `open(item)` 无 session 仍走 current |

## 仍阻塞 / 未宣称完成

- A09 Web：仍 online-first；禁止第二套 Outbox。需 Owner 才做浏览器 admission。
- C01：未从两端真实 UI 贯穿新增 JPY/USD。
- C03：日用安装禁止访问。
- C04：Gmail 三份最终合同无本会话入口。
- 本候选 Actions run 在审查时为 0；本轮只跑了下列窄门，不是全仓门禁。

## 本轮实际执行

- Web：`pytest tests/test_web_recurring_occurrences.py tests/test_web_expense_undo.py::test_web_reject_from_recurring_occurrence_returns_to_the_original_period tests/test_web_period_payment_fx_link_journey.py::test_period_payment_fx_confirm_return_then_explicit_link_zeros_reserve_once` → **9 passed**
- Android JVM：`:app:testGrayDebugUnitTest` 过滤 `RecurringOccurrencePaymentPickerTest` / `RecurringPeriodPaymentSurfaceTest` / `RecurringOccurrenceViewModelTest` / `ExpenseManualCreateOfflineTest` → **BUILD SUCCESSFUL**
- 未执行：完整 Android 应用、PostgreSQL 全集成、日用环境、Codex、merge。

## 唯一下一步

独立审查本分支最新 CODE_HEAD。不 merge，除非 Owner 明确要求。不装日用。
