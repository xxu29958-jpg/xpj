# P4 模拟器 connected 运行（2026-09-15）

CODE 未提交。工作区相对 AUDIT_BASE `c34efb40`。ADB 当时只有 `emulator-5554`，无实体机。

## 目标

`ticketbox_api36_host`（`sdk_gphone64_x86_64`，serial `emulator-5554`，`sys.boot_completed=1`）。

命令（cwd `repo\android`）：

```
ANDROID_SERIAL=emulator-5554
ANDROID_HOME=local Android SDK
.\gradlew.bat --no-daemon :app:connectedGrayDebugAndroidTest
  -Pandroid.testInstrumentationRunnerArguments.class=com.ticketbox.ui.screens.RecurringEditorRestorationTest,com.ticketbox.data.repository.RecurringOccurrenceRoomContinuityTest
```

## 仪器结果（已执行）

`TEST-ticketbox_api36_host(AVD) - 16-_app-gray.xml`：`tests="8" failures="0" errors="0"`。  
logcat runner：`OK (8 tests)`。HTML 报告：100%。耗时约 21s + 编译，Gradle wall `2m 3s`。

| 类 | 用例 | 结果 |
|---|---|---|
| RecurringEditorRestorationTest | recordedJpyAndRawInputSurviveRestorationUnderAnotherDefault | passed |
| RecurringEditorRestorationTest | cnyCreateEntryKeepsSelectedJpyAmountAfterRestoration | passed |
| RecurringEditorRestorationTest | targetDraftOccBaselineAndAttemptRestoreAsOneEditorSession | passed |
| RecurringEditorRestorationTest | editorEpochMismatchDropsRestoredEditorSession | passed |
| RecurringEditorRestorationTest | runtimeMismatchDropsRestoredEditorSession | passed |
| RecurringOccurrenceRoomContinuityTest | userSelectionSurvivesRoomRestartAndUnknownResponseThenExplicitUndo | passed |
| RecurringOccurrenceRoomContinuityTest | unpaidPeriodWithoutConfirmedStreamOpensExistingManualSheetFromRecordPayment | passed |
| RecurringOccurrenceRoomContinuityTest | savedPriorPeriodCanBeIdentifiedWhenReopenedWithUnavailablePeriodRead | passed |

这证明：隔离树上的 Compose 恢复（含 CNY 入口选 JPY 1200）和期次 Room 连续性在该 AVD 上跑过。  
**不证明**：用户从真实新增固定支出界面创建 JPY/USD 后付款、FX、确认、回原期次定位这一笔（C01）。仪器测试用 fixture / in-process 会话，不是整 app 主旅程。

## Gradle 任务失败（资格门，不是这 8 个用例红）

`:app:connectedGrayDebugAndroidTest` exit 1：`GrayDebug connected-test qualification failed with exit code 1`。

原因：任务 `doLast` 跑 `verify_android_test_qualification.py connected`，基线 `android/audit/test_count_baseline.txt` 的 `instrumentation=57`。本次过滤只跑 8 个，资格门按全量计数拒绝。仪器 XML 的 `test-result-exit-code.txt` 为 `0`。

不得把 Gradle FAILED 写成这 8 个测试失败，也不得把过滤跑当成 57 条 connected 门禁通过。

## Hyper-V `Ticketbox-Clean-4d76e6eb`（未执行）

Running，uptime ~18 天。manifest：`network_adapters: 0`，`state: clean_os_checkpoint_ready`，subject `4d76e6eb`，计算机名 `TBX-QUAL-01`。无网卡，不能拷包/SSH/浏览器。这是 Windows 发行资格干净机，不是本任务 Web 夹具。未加网卡、未装 APK、未改检查点。

## 未执行

- 全量 `connectedGrayDebugAndroidTest`（57）
- Clean VM 内 Web
- 日用安装
- 真机
- 从真实新增界面贯穿付款
