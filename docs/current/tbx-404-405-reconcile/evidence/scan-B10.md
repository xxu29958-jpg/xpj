# B10 跨月精确定位（主控初扫 `c34efb40`）

扫描：TRACED
当前能力：REGRESSED（相对 #405 `return_payment_expense_id`；现网返回只带 series+month）
修复：PROPOSED（Web 返回/草稿携带本次付款 id；Android 对等焦点）
证据等级：源码对照。未跑八月义务九月付款实机。

## Web

- 记录付款入口：`web_recurring_occurrences.py` L74–82 `flow_href("/web/expenses/new", return_to=recurring_occurrence, return_recurring_public_id, return_month=occurrence.period)`。
- 创建成功：`web_expense_create.py` L331–336 若 return_to=recurring_occurrence，redirect 到 **账单编辑页** 并保留 return 字段，不是直接回期次页并高亮付款。
- 回到期次：`resolve_return_to` L165–167 → `/web/recurring/{series}/occurrence`。
- `return_context_params` L190–195 对 recurring_occurrence **只回传 month**，没有 payment_id。
- 期次页另有 `payment_month` 查询（L95）——可换付款月份，不是“本次付款 id”。

## Android

全仓 `preferredExpenseId` 无匹配。`RecurringPaymentJourneyRouteTest.kt` 仅存在于未合 #405（PR 文件 added），AUDIT_BASE 无此测试文件。

## 对照旧 #405 `c0279d86`

- Android：`RecurringOccurrenceRoute` 把 `preferredExpenseId = original?.acceptedExpenseId` 传给 picker；picker 用 id 滤出本次付款，不依赖用户改月份。
- Web：`ExpenseReturnContext.return_payment_expense_id` → `return_context_params` 的 `payment_id`；occurrence GET 读 `payment_id`，`_focused_payment` 解析该笔。
- AUDIT_BASE：上述符号不在 main。`preferredExpenseId` 全仓无匹配。返回只带 month。

## 用户后果

八月义务、九月付款、FX/确认后回到原期次：能回到原 series+obligation month，但不能自动选中**这一笔**付款。手动搜索入口仍在（月份+query 字段）。
