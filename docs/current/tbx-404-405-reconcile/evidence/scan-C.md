# C 接缝（AUDIT_BASE `c34efb40`）

## C01 两端主旅程

扫描：TRACED（源码拼接）；当前能力：UNVERIFIED（且被 B01 挡住真实新增起点）
修复：BLOCKED until B01 修复后实跑
证据：Web `test_web_period_payment_fx_link_journey.py` 从 **API 预置** USD 计划走到付款→FX 编辑→确认→返回原月→explicit link。Android #405 `RecurringPaymentJourneyRouteTest` 不在 main。

真实新增 JPY/USD 计划入口在 AUDIT_BASE 不存在（B01）。不得把预置计划测试写成 C01 已验证。

## C02 #408/#410 与 #409/#413

扫描：TRACED（归类）
- #408 merge `e4e8dcc0`、#410 merge `d11341e9`：事件循环 / PowerShell 探针，**不是** #404 产品主体。本任务只做相关回归归属，不重开 Windows 生命周期。
- #409 merge `0cba9544`、#413 merge `275de599`：PendingViewModel reject/undo 消费，并入 A09/A10，不单独当产品。

当前能力：OUT_OF_SCOPE（408/410 产品面）/ 待 A09/A10 判定（409/413）
修复：NOT_NEEDED

## C03 日用只读

扫描：BLOCKED
当前能力：OUT_OF_SCOPE
修复：BLOCKED
合同禁止访问日用数据根、安装、绑定、导入。本会话未读日用 DB。

## C04 缺证

扫描：BLOCKED（部分）
- Gmail 三份最终合同：无会话入口 → `BLK-GMAIL`
- `docs/current/TICKETBOX_RECURRING_PAYMENT_JOURNEY_CONTRACT.md` 文件不存在 → 用 occurrence 合同 + #405/#412/#414 diff
不停止其余源码扫描。不得把缺证标成验收通过。
