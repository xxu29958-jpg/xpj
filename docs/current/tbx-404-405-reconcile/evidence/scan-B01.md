# B01 链路卡（主控，AUDIT_BASE `c34efb40`）

扫描：TRACED
当前能力：MISSING（相对 #405 创建入口；#415 `14c9eca8` 有切片但未合入 AUDIT_BASE）
修复：PROPOSED（不得在扫描未闭合前合生产；#415 可作最小补丁候选，须核对消费者）
证据等级：固定 SHA 源码。本条未把实机创建当已验证。

## 真实入口

- Android：固定支出编辑器新建。`RecurringEditorHostState.openCreate` 以账本显示币种打开会话。
- Web：`GET /web/recurring` 创建表单 POST `/web/recurring/create`。

## 链

1. Android 会话币种不可改
   - `c34efb40` `android/app/src/main/java/com/ticketbox/ui/screens/recurring/RecurringEditorSession.kt` `RecurringEditorSession.homeCurrencyCode` L61：`val`，无 `selectCurrency`。
2. Web 创建口锁隐藏账本币种
   - `c34efb40` `backend/app/templates/web/recurring.html` 创建 form L253–256：`<input type="hidden" name="home_currency_code">`，无 `id="rc-add-currency"`。
3. 后端 writer 已接受计划币种（不是缺口 owner）
   - `web_recurring.py` POST create 读 `home_currency_code` + `parse_baseline_yuan`；`create_manual_recurring_item` 写 item.home_currency_code，occurrence_count=0。
4. 对照
   - 旧 #405 `c0279d86`：创建 select + `selectCurrency`。
   - 未合 #415 `14c9eca8`：同入口已补；JVM/Web 测试已跑过（前次会话），仪器恢复测试在模拟器 5/5。

## 判定

不能在 AUDIT_BASE 从真实新增入口创建 JPY 1200 / USD 12.34。不得用预置外币计划证明本条。账本本位币路径本身仍 CNY。

## 未用本条冒充

B02 历史记录锁定、B03 列表估值、B04 付款入口另卡。
