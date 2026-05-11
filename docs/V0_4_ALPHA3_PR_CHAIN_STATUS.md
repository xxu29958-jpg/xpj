# v0.4-alpha3 PR Chain Status

> 截至 v0.4-alpha4 开工时间点。

## PR #14 — slice2 / Reports & Data Quality

| 字段 | 值 |
|---|---|
| 标题 | v0.4-alpha3 slice 2 — Reports / Data Quality / Architecture Hardening |
| Head | `d2ba375` |
| 状态 | open / draft=false / mergeable=true |
| Commits | 28 |
| Changed files | 81 |
| 完成模块 | M0 结构治理、M1 Android Reports、M2 Monthly Goal、M3 Merchant/Category、M4 Data Quality、M5 CSV、M6 Duplicates、M8 Owner、M9 Docs/Runbook |
| 部分完成 | M7 Android Review 快速操作（已转移到 PR #15） |
| 历史债 | PendingScreen 693、ExpenseEditScreen 634、LedgerScreen 740、ExpenseRepository 516 |
| PR body 滞后点 | 文案仍写"draft / in progress"；metadata 已是 ready candidate |
| 建议 | 更新 PR body 后视为 slice2 ready candidate，可合可不合（取决于 release 节奏） |

## PR #15 — slice3 / Android Review Workflow + Historical Debt Split

| 字段 | 值 |
|---|---|
| 标题 | v0.4-alpha3 slice 3: Android Review Workflow + Historical Debt Split |
| Head | `72368cf` |
| 状态 | open / draft=true / mergeable=true |
| Commits | 30 |
| Changed files | 111 |
| 完成 | PendingScreen 725→225 拆分、五套 BottomSheet（QuickCategory / QuickMerchant / MissingAmount / BulkConfirm / DuplicateConfirm）、PendingViewModelReviewActions、ExpenseEditScreen 659→280、LedgerScreen 765→126、ANDROID_DEBT_BACKLOG P1 勾完、PendingScreen.kt UTF-8 乱码修复 |
| 单测 / lint / assemble / encoding | 全绿 |
| 留待 alpha4 | PendingViewModel review actions 单测、Emulator 手工验收、真机灰度验收 |
| 建议 | 不再扩功能；alpha4 在新分支上补单测 + 验收，再决定是否将 alpha4 合入 PR #15 或单独开 PR |

## alpha4 接力点

- 分支：`v0.4-alpha4-mobile-architecture-rc`，基于 PR #15 head `72368cf`
- 必做：
  1. 抽 `PendingReviewActions` 接口（done in this branch）
  2. 补 PendingViewModel review actions 单元测试（done in this branch）
  3. Emulator acceptance runbook 落文（done in this branch）
  4. Real-device acceptance runbook 落文（done in this branch）
- 不做：CSV / Owner / web 模块新功能

## 后续建议（按时间线）

1. PR #14 mark ready（更新 body）→ merge 到 main
2. PR #15 alpha4 改动合入 → 走 Review Pass → mark ready → merge
3. tag `v0.4-alpha3-rc1`，按 RC runbook 走真机验收
4. 真机通过后再切 v0.4-beta1
