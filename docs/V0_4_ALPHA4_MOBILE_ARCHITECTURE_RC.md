# v0.4-alpha4 — Mobile Architecture Stabilization + RC Readiness

> 状态：进行中（commit base = v0.4-alpha3-slice3 head `72368cf`）
> 分支：`v0.4-alpha4-mobile-architecture-rc`

## 一句话目标

把 PR #14（slice2 ready candidate）+ PR #15（slice3 Android Review Workflow + Historical Debt Split）两个大包沉淀成可以进入 v0.4-alpha3 RC 的移动端稳定版：补 PendingViewModel review actions 单元测试、确认 P1 大文件拆分到位、为 Repository 做依赖反转、把模拟器 / 真机验收 runbook 落文。

## 基线

| 项 | 状态 |
|---|---|
| PR #14 slice2 reports/DQ/arch | ready candidate（已 mark draft=false） |
| PR #15 slice3 review workflow | open / draft=true，待测试 + 验收 |
| 真机 | Xiaomi 2410DPN6CC 在册但 gray flavor 指向 production；本地 backend 无法直接喂数据 |
| PendingScreen.kt | 225 行（< 280 ✅） |
| ExpenseEditScreen.kt | 280 行（== 280 ✅） |
| LedgerScreen.kt | 126 行（< 280 ✅） |
| ExpenseRepository.kt | 576 行（依然超阈，本轮做接口反转，完整切分延期） |
| PendingViewModel.kt | 255 行（< 360 ✅） |
| PendingViewModelReviewActions.kt | 231 行（< 360 ✅） |

## 允许范围

- 抽 `PendingReviewActions` 接口，把 `PendingViewModel` 解耦出 `ExpenseRepository`
- 补 PendingViewModel review actions 单元测试（QuickCategory / QuickMerchant / MissingAmount / BulkConfirm / DuplicateAction）
- 把 `ExpenseRepository` 标记为接口实现，但不强拆 Repository 子文件
- 文档落地（本文件、PR_CHAIN_STATUS、EMULATOR_ACCEPTANCE、REAL_DEVICE_ACCEPTANCE）

## 禁止范围

- 不动 Room schema、不新增依赖
- 不动身份 / token / ledger switch / 上传主链路
- 不做 v0.5 家庭成员、不做新后端功能、不做新 /web 功能
- 不做完整 recurring / budget / 通知监听
- 不让 UI 直接调 Retrofit / Room
- 不让 Repository 返回 DTO / Entity 给 UI

## 测试矩阵（必跑）

```powershell
cd E:\projects\xiaopiaojia\android
.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
.\gradlew.bat --no-daemon :app:assembleGrayDebug :app:assembleInternalDebug
.\gradlew.bat --no-daemon :app:lintGrayDebug
```

```powershell
cd E:\projects\xiaopiaojia
git diff --check
powershell -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_project.ps1
```

## RC 门槛

- Android `testGrayDebugUnitTest` 全绿且包含 PendingViewModelReviewActions 用例
- gray + internal flavor `assembleDebug` + `lintGrayDebug` 全绿
- `verify_project.ps1`、文本编码、`git diff --check` 全绿
- Emulator acceptance 已走过一遍（参见 [V0_4_ALPHA4_EMULATOR_ACCEPTANCE.md](./V0_4_ALPHA4_EMULATOR_ACCEPTANCE.md)）
- Real-device acceptance：参见 [V0_4_ALPHA4_REAL_DEVICE_ACCEPTANCE.md](./V0_4_ALPHA4_REAL_DEVICE_ACCEPTANCE.md)；本轮可标记 Pending，但必须有 runbook

## 与 v0.5 的边界

v0.4-alpha4 只做"稳定 + RC 准备"。家庭成员、银行聚合、长周期 recurring、完整预算等放到 v0.5 之后。
