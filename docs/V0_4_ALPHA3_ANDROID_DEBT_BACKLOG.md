# Android 历史债 Backlog

> 用于跟踪 v0.4-alpha3 期间发现、暂未在当轮 PR 内处理的大文件 / 结构问题。

## 优先级 P1（下一轮 PR 必拆）

### ExpenseEditScreen.kt（659 → 280）✅ 已在 slice 3 follow-up 拆完

- 入口 `ui/screens/ExpenseEditScreen.kt` 现 280 行（G2 阈值），仅负责状态 wiring 与高层布局。
- 抽出的子文件位于 `ui/screens/expense/`：
  - `ExpenseEditFields.kt`（`EditDraftPreviewCard` / `OcrProgressCard` / `SelectableCategoryChip` / `ExpenseDateField`，221）
  - `ExpenseEditDialogs.kt`（`ExpenseEditDatePicker` / `ExpenseEditTimePicker` / `ExpenseEditRejectDialog`，119）
  - `ExpenseEditActions.kt`（`ExpenseEditPrimaryActions` / `ExpenseEditConfirmActions`，77）
  - `ExpenseEditMoreSection.kt`（标签/价值分/后悔分/原文 折叠面板，101）
  - `ExpenseEditCoreFields.kt`（`AmountField` / `MerchantField` / `CategoryField` / `NoteField` / `SourceInfo`，约 100）
- 验证：`:app:compileGrayDebugKotlin`、`:app:testGrayDebugUnitTest`、`:app:lintGrayDebug`、`:app:assembleGrayDebug :app:assembleInternalDebug` 均通过。

### LedgerScreen.kt（765 → 126）✅ 已在 slice 3 follow-up 拆完

- 入口 `ui/screens/LedgerScreen.kt` 现 126 行（G2 阈值内），仅持有 3 个 BottomSheet 显示状态 + 顶层布局。
- 抽出的子文件位于 `ui/screens/ledger/`：
  - `LedgerFilters.kt`（`LedgerFilterPanel` / `LedgerInlineFilters` / `LedgerInlineButton`，144）
  - `LedgerToolsSheet.kt`（导出 / 更新 / 清除筛选 BottomSheet，101）
  - `LedgerHeader.kt`（标题 + 记一笔按钮，69）
  - `LedgerSummary.kt`（合计卡片 + 趋势点带，118）
  - `LedgerItems.kt`（`LedgerDayHeader` / `LedgerExpenseCard` / `LedgerCategoryMark`，129）
  - `LedgerEmptyState.kt`（空态卡片 + 插图，130）
  - `LedgerStatusText.kt`（`ledgerCombinedStatusLine` / `ledgerFilterSummary` / `ledgerSyncClock` 工具函数，29）
- 验证：与上同。

## 优先级 P2（择期处理）

### ExpenseRepository.kt（516 行）

- 当前打包了：身份绑定、上传、CRUD、duplicate、CSV、stats、recurring、data quality、category rules、image。
- 建议拆分（slice 4 或 v0.5）：
  - `ExpenseReviewRepository`（CRUD + duplicate + confirm/reject）
  - `StatsRepository`（monthly / lifestyle / recurring / dataQuality）
  - `ExportRepository`（CSV）
  - `CategoryRuleRepository`
  - 保留 `ExpenseRepository` 仅负责 fetch / upload 主链路
- 风险：调用点多（ViewModelFactory），需同步更新。

### LedgerManualExpenseSheet.kt（286 行）

- 当前 286 行，略超 280 阈值。BottomSheet 阈值惯例 ≤ 220，可放宽到 320。
- 建议：抽出 `ManualExpenseAmountField` / `ManualExpenseCategoryDropdown` 等小组件。

### settings/SettingsAppearanceComponents.kt（341 行）/ SettingsServerComponents.kt（355 行）/ SettingsBackgroundComponents.kt（374 行）

- 都是历史"杂项组件聚合文件"。
- 建议按职能拆为单独 Composable 文件，每个 ≤ 220 行。

## 不打算处理（保持现状）

- `ui/screens/StatsScreen.kt` 137 行 ✅
- `ui/screens/stats/` 子包 8 张卡片 ≤ 198 ✅
- 所有 ViewModel ≤ 360 行 ✅

## 复测命令

```powershell
cd e:\projects\xiaopiaojia\android
.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
.\gradlew.bat --no-daemon :app:assembleGrayDebug :app:assembleInternalDebug
.\gradlew.bat --no-daemon :app:lintGrayDebug
```
