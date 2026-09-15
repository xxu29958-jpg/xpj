# 已执行验证（B01/B07 改码后）

CODE 未提交。工作区相对 AUDIT_BASE `c34efb40` 含 B01（自 #415 `14c9eca8` 取出 8 文件）与 B07（`createManualExpense(draft, expectedBinding)` → `bindExact`）。

## 已执行且通过

- Web：`pytest tests/test_web_recurring_form_continuity.py -q`  
  解释器：`backend venv python`  
  cwd：`repo\backend`  
  结果：**8 passed**（13.58s）
- Android JVM：`gradlew :app:testGrayDebugUnitTest` 过滤  
  `RecurringOccurrenceViewModelTest`、`RecurringPeriodPaymentSurfaceTest`、`RecurringCapturedCurrencyEditorTest`  
  结果：**BUILD SUCCESSFUL**（约 1m 6s）。本 worktree 未找到 `test-results/*.xml` 计数文件，故不把具体 case 数写成已核验。

## 未执行（本文件当时）

仪器/模拟器已另记 [run-P4-emulator.md](run-P4-emulator.md)：过滤 8 passed；Gradle 全量资格门未过。

仍未执行：

- 真实新增 JPY/USD 计划后付款（C01）
- B05/B10 草稿与 payment_id 修复
- 日用安装

不得把 8 个 Web 表单连续测试写成「用户已能在真机创建外币计划」。
