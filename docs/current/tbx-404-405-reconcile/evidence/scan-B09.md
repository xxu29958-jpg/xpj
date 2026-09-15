# B09 付款进入 #404 FX/复核/确认（AUDIT_BASE `c34efb40`）

扫描：TRACED（接线）
当前能力：PRESERVED（与普通手动创建共用 FX owner）；运行 UNVERIFIED
修复：NOT_NEEDED（未发现第二套 FX）
证据等级：源码。Web 集成 `test_web_period_payment_fx_link_journey` 存在但**预置** USD 计划，不能证明 B01。Android 付款后 FX 实机未跑。

## 链

1. Web 创建：`create_manual_expense` `expense_service/_create.py` L190–226
   - 同事务 `prepare_pending_expense_fx`
   - commit 后 `submit_pending_expense_fx`
   - 成功 redirect：`web_expense_create.py` L331–336 → `/web/expenses/{id}/edit` 且保留 recurring return 字段。
2. Android：`createPeriodPayment` → `ledger.createManualExpense` → `enqueueLocalCreate`（CreateExpense Outbox）。同步后账单进入既有 #404 pending FX / 编辑器，不是期次 VM 另写汇率。
3. 自动 FX vs 手工汇率：编辑器/确认走既有 A03 路径；本期未发现 period-payment 旁路覆盖人工汇率。需在 A03 卡交叉引用，不在本条重复判完。
4. 确认不清预留：见 B11；`test_web_period_payment_fx_link_journey` 断言 FX/确认后仍须 explicit link。

## 限制

C01 从「真实新增 JPY 计划」贯穿本条：被 B01 挡住。本条只证明**已有外币期次**的付款可进入同一 FX owner。
