# B03 列表/期次/计划估值（AUDIT_BASE `c34efb40`）

扫描：TRACED（展示边）
当前能力：PRESERVED（原币展示；跨币换算不在客户端做）
修复：NOT_NEEDED（本条未发现接线缺失）
证据等级：源码。未跑预算/建议页实机。

## 链

1. 固定支出列表金额
   - `RecurringItemSections.kt` L217：`recurringRecordedAmountText(item.baselineAmountCents, item.homeCurrencyCode)`。
   - `RecurringMoneyViews.kt` L16–24 `recurringTotalLines`：按币种分行；注释写明跨币换算是后端投影。
   - L28–34：可解析币种按最小单位格式化；空码显示未知金额；不支持码走 `CurrencyDisplay.forRecord`。
2. 期次页
   - `RecurringOccurrenceSheet.kt` L63–65：预留/已付分别用 `occurrence.homeCurrencyCode` / `paidHomeCurrencyCode`。
   - Web `recurring_occurrence.html` L22/L49：计划与已付各带自己的币种字段。
3. Web 列表
   - `recurring.html` L87–97：baseline / 本月 / 月均都带 `item.home_currency_code`，不是账本显示币种改写。
4. 计划不能伪装付款
   - 期次 `state` 与 `expensePublicId` 分开；未 explicit link 前仍 `unfulfilled`（见 B11）。

## 未用本条冒充

B01 创建入口、B09 付款后 FX。预算/建议页若另有换算消费者，见 A12 共享估值日期语义。
