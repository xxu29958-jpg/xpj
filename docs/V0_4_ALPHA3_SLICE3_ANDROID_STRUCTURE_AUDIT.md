# v0.4-alpha3 Slice 3 — Android Structure Audit

> 体检日期：2026-05-11（slice 3 起点，基于 head `d2ba375`）

## 当前 Android 主目录大文件

| 文件 | 当前行数 | 阈值 | 状态 | 本轮处理 | 阻塞 M7？ |
|---|---:|---:|---|---|---|
| `ui/screens/PendingScreen.kt` | 725 | 280 | ❌ 超 | **本轮拆分到 `ui/screens/pending/` 子包** | 是 |
| `ui/screens/LedgerScreen.kt` | 740 | 450 | ❌ 超 | 延期 → `ANDROID_DEBT_BACKLOG` | 否 |
| `ui/screens/ExpenseEditScreen.kt` | 634 | 450 | ❌ 超 | 延期 → `ANDROID_DEBT_BACKLOG` | 否 |
| `data/repository/ExpenseRepository.kt` | 516 | 420 | ❌ 超 | 本轮评估拆分（如继续膨胀则拆 ReviewActionRepository） | 否（本轮新增的 review action 都复用既有方法） |
| `ui/screens/StatsScreen.kt` | 137 | 280 | ✅ | — | 否 |
| `ui/screens/stats/` 8 个卡片 | 全部 ≤ 198 | 220 | ✅ | — | — |
| `viewmodel/PendingViewModel.kt` | 204 | 360 | ✅ | 本轮扩展（目标 ≤ 360） | — |
| `viewmodel/SettingsViewModel.kt` | 306 | 360 | ✅ | — | — |
| `ui/screens/SettingsScreen.kt` | 215 | 280 | ✅ | — | — |
| `ui/screens/LedgerManualExpenseSheet.kt` | 286 | 280 | ⚠ 略超 | 延期，BottomSheet 阈值放宽到 320 是合理的，但记录于 backlog | — |
| `ui/screens/settings/AppearanceScreen.kt` | 226 | 280 | ✅ | — | — |
| `ui/screens/settings/SettingsAppearanceComponents.kt` | 341 | 280 | ⚠ 略超 | 延期 → backlog | — |
| `ui/screens/settings/SettingsServerComponents.kt` | 355 | 280 | ⚠ 略超 | 延期 → backlog | — |
| `ui/screens/settings/SettingsBackgroundComponents.kt` | 374 | 280 | ⚠ 略超 | 延期 → backlog | — |

## 本轮拆分目标

将 `PendingScreen.kt` 拆为以下结构：

```
ui/screens/pending/
  PendingComponents.kt        # PendingTop / Hero pill / Hero metric
  PendingEmptyStates.kt       # Loading / Empty / UploadFlowCard / UploadProgressCard / FlowStep / PendingMessageCard
  PendingHeader.kt            # PendingHeader + PendingToolsSheet + PendingDisplayMode
  PendingFilters.kt           # NeedsReviewFilter + applyNeedsReviewFilter + NeedsReviewFilterBar + EmptyFilterCard
  sheets/
    QuickCategorySheet.kt
    QuickMerchantSheet.kt
    MissingAmountSheet.kt
    BulkConfirmSheet.kt
    DuplicateConfirmSheet.kt
ui/screens/PendingScreen.kt   # 入口：state wiring + sheet dispatch + 列表组装（目标 ≤ 280 行）
```

## ExpenseRepository 评估

本轮新增的 review action 全部复用既有方法：

- 补分类 / 补商家 / 补金额：`updateExpense(id, ExpenseDraft)` ✅ 已存在
- 保存并确认：`updateExpense` + `confirmExpense` ✅ 已存在
- 批量确认：循环 `confirmExpense` ✅ 已存在
- 疑似重复保留：`markNotDuplicate` ✅ 已存在
- 疑似重复忽略：`rejectExpense` ✅ 已存在

结论：**本轮不强制拆分 ExpenseRepository**；新增方法 0，文件继续保持 516 行。下一轮（slice 4 或 v0.5）再考虑拆出 `ReviewActionRepository / StatsRepository / ExportRepository` —— 已记录于 `ANDROID_DEBT_BACKLOG.md`。

## 闸门结论

- 新增文件：全部 ≤ 220 行（BottomSheet 子文件阈值）✅
- PendingScreen.kt：目标 ≤ 280 行 ✅
- PendingViewModel.kt：目标 ≤ 360 行（当前 204；扩展 ~150 行进入预算上限附近）⚠
- ExpenseRepository.kt：不动 ✅
