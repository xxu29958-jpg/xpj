# B11 明确关联才履约（AUDIT_BASE `c34efb40`）

扫描：TRACED
当前能力：PRESERVED（#412/#414）
修复：NOT_NEEDED
证据等级：源码 + Web 集成测试存在（预置计划）。未在本任务 HEAD 重跑该测试。

## 链

1. Android 选择：`RecurringOccurrenceViewModel.choose` L149–168 → `OccurrencePaymentDraft.request.action` = `link` 或 `clear`。
2. 提交：`submit` L170–187 → `repository.enqueue(binding, choice)`。Owner 是既有 occurrence command，不是 create writer。
3. UI：`RecurringOccurrenceSheet` 记录付款 / 选择已有账单 / 解除 分按钮（L71–85 vs L75–82 vs picker）。
4. 确认不清预留：`confirmCompletionRestoresOriginalPeriodWithoutFulfillingUntilExplicitLink` 恢复八月后 `unfulfilled`，`actions.submissions` 仍空。
5. Web：POST `web_set_recurring_occurrence` → `set_occurrence_payment`。`test_web_period_payment_fx_link_journey`：FX/确认后 explicit link 才把预留清零。

## 排除解释

不得把记录付款或 FX 完成当成履约。不得新建第二套关联 writer。
