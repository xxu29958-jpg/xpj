# v0.4-alpha3 Slice 3 — Android Review Workflow + Historical Debt Split

> Branch: `v0.4-alpha3-slice3-android-review-workflow`
> Base: PR #14 head `d2ba375`（slice 2 ready candidate）
> 模型：Copilot Pro+ Claude Opus 4.7（不依赖 Codex）
> Android 真机暂未连接，本轮允许 Emulator 验证；真机验收挂到 RC。

## 目标

让 Android 不只是能看报表，而是能 **快速整理待确认账单**：

1. PendingScreen 上 4 套 BottomSheet 快速操作（补分类 / 补商家 / 补金额 / 批量确认）。
2. 疑似重复必须二次确认；保留 / 忽略两条路径都明确。
3. 拆 PendingScreen.kt 到 `ui/screens/pending/` 子包，把单文件控制在 G2 阈值内。
4. 评估 ExpenseRepository 进一步拆分。
5. 记录 ExpenseEditScreen / LedgerScreen 历史债处理计划。

## 允许范围

- `ui/screens/pending/` 子包新文件
- `viewmodel/PendingViewModel.kt` 增加 review action 状态与事件（保持 ≤ 360 行；如超阈则拆 delegate）
- `data/repository/ExpenseRepository.kt` 仅在必要时拆 `ReviewActionRepository`
- Compose / ViewModel 单测
- 文档：本文件 + `V0_4_ALPHA3_SLICE3_ANDROID_STRUCTURE_AUDIT.md` + `V0_4_ALPHA3_ANDROID_DEBT_BACKLOG.md`

## 禁止范围（严格）

- 不改 Room schema
- 不新增三方依赖
- 不改后端 API（除非已有接口无法支持，本轮判定：已有 `PATCH /api/expenses/{id}` + `POST /confirm` + `markNotDuplicate` 已足够）
- 不改身份 / token / ledger switch / 上传主链路
- 不动 CSV / Owner / Web 模块
- 不让 UI 直接调用 Retrofit / Room
- 不静默确认疑似重复
- 不绕过 `amount_required`
- 不做完整 recurring / 完整预算 / v0.5 家庭成员

## 工程闸门（G2 大文件）

| 层 | 阈值（行） |
|---|---:|
| Compose Screen 入口 | 280 |
| 单 Composable 函数 | 90 |
| BottomSheet 单文件 | 220 |
| ViewModel | 360 |
| Repository | 420 |

## 验收命令

```powershell
cd e:\projects\xiaopiaojia\android
.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
.\gradlew.bat --no-daemon :app:assembleGrayDebug :app:assembleInternalDebug
.\gradlew.bat --no-daemon :app:lintGrayDebug

cd e:\projects\xiaopiaojia
git diff --check
powershell -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
```

后端如未触碰可跳过 pytest；触碰则全套（compileall/ruff/pytest/smoke）。

## 当前历史债（输入）

| 文件 | 行数 | 处理 |
|---|---:|---|
| `ui/screens/PendingScreen.kt` | 725 | **本轮拆分**（slice 3） |
| `data/repository/ExpenseRepository.kt` | 516 | 评估，必要时拆 ReviewActionRepository |
| `ui/screens/ExpenseEditScreen.kt` | 659 → 280 | ✅ 已在 slice 3 follow-up 拆完（详见 `V0_4_ALPHA3_ANDROID_DEBT_BACKLOG.md`） |
| `ui/screens/LedgerScreen.kt` | 765 → 126 | ✅ 已在 slice 3 follow-up 拆完（详见 `V0_4_ALPHA3_ANDROID_DEBT_BACKLOG.md`） |

## 真机验收策略

- Emulator 内置 backend 地址：`http://10.0.2.2:8000`
- 完成报告必须写 `Android validation = Emulator only / Real-device validation = Pending`
- BiometricPrompt / Photo Picker / 长期使用真机走查留到 RC 阶段
