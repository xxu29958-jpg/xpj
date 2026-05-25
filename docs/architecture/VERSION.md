# 版本真值源

本文件是小票夹"版本号"的唯一权威来源。任何 README、API、CI、运维脚本若需引用版本，必须以本文件为准，并保持与下表的代码位置同步。

## 当前版本

| 维度 | 版本 | 代码位置 |
|------|------|----------|
| 后端 `BACKEND_VERSION` | `1.2.0` | [backend/app/version.py](../../backend/app/version.py) |
| 后端 `IDENTITY_SCHEMA_VERSION` | `v0.3` | [backend/app/version.py](../../backend/app/version.py) |
| Android `versionName` | `1.2.0` | [android/app/build.gradle.kts](../../android/app/build.gradle.kts) |
| Android `versionCode` | `10200000` | [android/app/build.gradle.kts](../../android/app/build.gradle.kts) |

> Android internal 构建会自动追加 `-internal` 后缀；正式发布请走 release 配置。

## 阶段标签

- v0.9.0a1：Reports / Goals / Dashboard 卡片配置 + Vico 图表 + `/web` ECharts 收口。
- v1.0.0：商品级小票 line items (ADR-0035) / 家庭拆账邀请 (ADR-0029) / 后台任务执行模型 (ADR-0030) / `/web` 公网 PWA shell (ADR-0028 + Issue #20) / v0.9 → v1.0 cut-over + 30 天 rollback CLI (ADR-0031)。`identity_schema=v0.3` 不变。
- v1.2.0：v1.1 现金流预算主线 + v1.2 learning-feedback + OCR facts 单源**合并发布**（无单独 v1.1.0 tag）。
  - **v1.1 现金流预算 + 自托管 AI Provider (ADR-0036)**：BudgetAdvisor Protocol + EmptyBudgetAdvisor + OpenAiCompatBudgetAdvisor（OpenAI-compat 统一协议，local LLM + 云端 API 一套接口）、alias maps + outbound payload guard（脱敏边界）、冷启动基线 50/30/20 + BLS 2024 anchor、个人 P50/P75 + default-personal blend + discretionary 公式、`monthly_income_plan` model + service + CRUD routes、`/api/budget/advise` anonymising builder + provider integration、`/web` income-plans + budget-advise pages、Android income plan vertical slice + Settings 导航。
  - **v1.2 Learning Feedback Dual Tables (ADR-0037)**：`algorithm_decisions` / `ledger_learning_events` / `ocr_facts` 三张 append-only 表 + tenant 隔离 + retention + cleanup；algorithm registry + version 回滚；learning facts 与 advisor governance 打通；monthly report / insight radar 骨架。
  - **OCR facts 单源迁移 (5/5 步骤)**：`read_ocr_text` 单源 helper / backfill / drop fallback / column inert；fact-backed OCR enforce（`OCR_PROVIDER=empty` 下 retry 返回 503 `ocr_not_configured` contract）。
  - **工程化 / 安全**：6 个 service + `_migrations.py` / `_validate.py` 拆 sub-packages、web_expense_edit / web.css / Android SettingsViewModel / ExpenseDto 按职责拆、6 个测试文件按 endpoint/flow/entity 拆、公网 + maintenance gates 加固、CodeQL Android 分析。
  - `identity_schema=v0.3` 不变。
- v1.3（规划中）：自托管多端同步增强（Android/web 离线 ↔ 服务端冲突处理 / 重试 / 撤销，不接第三方云）；现金流预算 UI 收口（三端一致 + AI 建议确认流）；Migration framework / handwritten `_migrations.py` 进一步重构视情况开 ADR。

## 版本号约束

- `BACKEND_VERSION` 与 Android `versionName` 必须始终保持完全一致字符串。
- Android `versionCode` 与 `versionName` 的映射规则：`MAJOR * 10_000_000 + MINOR * 100_000 + PATCH * 1_000 + (alpha/beta 序号)`。当前 `1.0.0 → 10_000_000`。
- `IDENTITY_SCHEMA_VERSION` 只在 Account / Ledger / Device / AuthToken / UploadLink / PairingCode 契约变更时升级；v0.9 不动。
- 发布新版本时，**只改 [backend/app/version.py](../../backend/app/version.py) 与 [android/app/build.gradle.kts](../../android/app/build.gradle.kts) 顶部的 `ticketboxVersionCode` / `ticketboxVersionName`，然后同步更新本文件与 [README.md](../../README.md) 的"当前版本"段落**。其它脚本与文档不应硬编码版本字符串。

## 校验

合入前手动核对：

```powershell
# 后端
Select-String -Path backend\app\version.py -Pattern 'BACKEND_VERSION'
# Android
Select-String -Path android\app\build.gradle.kts -Pattern 'ticketboxVersionName'
# 文档
Select-String -Path docs\architecture\VERSION.md -Pattern '当前版本'
Select-String -Path README.md -Pattern '当前版本'
```

四处字符串必须一致。
