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
- v1.1：未发布。ADR-0036 (AI Budget Provider Privacy Boundary) 已 codify——v1.1 主线"家庭现金流预算"的 AI 集成边界在引入 provider 前先 codify，但本体推迟到后续版本。版本号跳过 1.1.0。
- v1.2.0：Learning Feedback Dual Tables (ADR-0037)——`algorithm_decisions` / `ledger_learning_events` / `ocr_facts` 三张 append-only 表 + learning service / ops 收口；OCR facts 单源迁移（`expense.raw_text` → `ocr_facts.raw_text`，5 步骤完成）。`identity_schema=v0.3` 不变。
- v1.3（规划中）：v1.1 跳号后的家庭现金流预算主线（收入计划 / 固定支出 / 跨月重复识别 / 本月预计消费 / 历史弹性基线 / 本地确定性预算公式 + 用户确认才落盘）+ 脱敏 AI provider（按 ADR-0036 边界实现）+ 自托管多端同步增强。Migration framework / handwritten `_migrations.py` 重构视情况开 ADR。

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
