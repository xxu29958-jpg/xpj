# v0.4-alpha3 — Smart Ledger Engine

> 子标题：Review + Reports + Rules + Recurring Candidates + Goal MVP
> 基线：`v0.4-alpha2-tri-surface-ui` PR #12 head `7bdf1a1`（v0.4-alpha2 Tri-Surface UI/UX，状态 open / mergeable=true / 未合并）
> 分支：`v0.4-alpha3-smart-ledger-engine`
> 范围：**功能推进大版本**。不是 UI polish，也不是安全边界复查。

---

## 🚩 RC1 状态（2026-05-11）

**v0.4-alpha3 已进入 RC1。** 基线 commit `c05e85f`（main），包含 PR #11 / #14 / #15 / #16 全部合并。

- 自动化矩阵全绿：292 pytest pass / Android 4 gates SUCCESS / 公网边界 35/35 PASS / 自用健康 11/11 OK。
- 真机走查通过：Android（Xiaomi 2410DPN6CC）+ iPhone（UploadLink）+ 多账本隔离均验证成功。
- 详细报告：`docs/V0_4_ALPHA3_RC1_REPORT.md` / `docs/V0_4_ALPHA3_RC1_KNOWN_ISSUES.md` / `docs/V0_4_ALPHA3_RC1_SCREENSHOTS.md`。
- Tag 计划：`v0.4-alpha3-rc1`（P0=0, P1=0）。

---

## 1. 版本目标

让小票夹从 **"能上传 + 能确认 + 能切账本"** 推进到 **"能整理 + 能识别 + 能建议 + 能洞察"**。

承接 v0.4-alpha2 已完成的三端信息架构与多账本基础设施，本期把后端从被动存储升级为 **智能账本整理引擎**：

- 规则可预览、可批量应用，但不自动确认
- 商家可归一聚合，但保留原文
- 固定支出可识别为候选，但不自动入账
- 月度目标可设置，但只读进度，不做分类预算
- /web 成为真正的 Review 工作台（批量分类 / 批量商家 / 批量确认 / 批量忽略）

## 2. 不做清单（严格）

- 不做家庭成员 / 多账号 / 邀请码 → v0.5
- 不做银行聚合 / 净资产 → 永不做
- 不做完整 Recurring 表（只输出候选）
- 不做分类预算 / rollover 预算
- 不做规则 DSL / regex（第一版仅 substring 匹配）
- 不自动确认任何账单
- 不自动改写已确认账单的分类
- 不改 schema（CategoryRule / Expense 表结构维持现状）
- 本版不引入图表库（Android 用 Compose 原生绘制；长期政策见 `docs/DECISIONS/0023-chart-library-policy.md`）

## 3. 能力域与任务编号

| 能力域 | 任务 |
|---|---|
| A 基线 | T01 alpha3 baseline + T02 capability audit |
| B Android Reports | T03-T08 + T28-T29 |
| C /web Review Center | T09-T15 + T34 |
| D Rules Engine | T16-T20 |
| E Merchant & Category | T21-T23 |
| F Recurring Candidate | T24-T26 |
| G Monthly Goal | T27-T30 |
| H Import / Export / DQ | T31-T34 |
| I Android Review 增强 | T35-T38 |
| J Owner 产品化 | T39-T41 |
| K 文档与验收 | T42-T45 |

## 4. 施工 PR 拆分

- PR A：Reports Engine（Android Stats 全面改造 + 本月目标）
- PR B：/web Review Center（批量操作 + Data Quality Dashboard）
- PR C：Rules + Merchant（规则预览 / 应用 / /web rules / 商家归一）
- PR D：Recurring + Goal + Import/Export
- PR E：Owner + Docs + RC

本期单 PR 不会承担多个 PR 的范围。

## 5. 安全不变式（沿用 alpha1 / alpha2）

- 公网仍仅暴露 `/api/*`，`/web` `/owner` 在公网继续 403
- 所有新增 API 必须经过 `get_current_app_context` 或 `_web_require_local`
- 所有新增服务必须按 `tenant_id` 隔离
- `LedgerRepository.switchLedger` / `ExpenseDao.findAnyByServerIds` 禁止触碰
- 无 token_hash / upload_key / 绝对路径泄漏（继续 `test_*_no_secret_leak` 覆盖）
- 无 Schema 破坏性迁移；如需新表必须 alembic 或等价 `Base.metadata.create_all` 兼容路径

## 6. 测试矩阵（最终汇总在 T45）

- `backend`：`compileall` / `ruff` / `pytest` / `smoke_test.py`
- `android`：`testGrayDebugUnitTest` / `assembleGrayDebug` / `assembleInternalDebug` / `lintGrayDebug`
- 总验证：`scripts\verify_project.ps1` / `git diff --check` / `scripts\check_text_encoding.ps1`

## 7. 回滚

- 所有改动可通过 `git revert` 单个 PR 实现
- 不依赖任何破坏性 schema 变更
- 上层数据库回退步骤同 alpha2：`git reset --hard 7bdf1a1`

## 8. 下一版（v0.4-beta1 / v0.5 候选）

- 家庭成员邀请 / 独立账号 / 隐私隔离 → v0.5
- 完整 Recurring 系统（用户确认候选 → 创建 recurring 记录 → 自动入账提醒）→ v0.4-beta1
- 分类预算 + rollover → v0.4-beta1
- /web Rules 规则 regex / 复合条件 → v0.4-beta1


---

## 9. 实施记录（本会话）

> 状态截至 commit 1d3f452 on branch 0.4-alpha3-smart-ledger-engine。

### 已完成（本期可发布）

| T# | 任务 | 状态 | 关键 commit |
|---|---|---|---|
| T01 | alpha3 baseline doc | ✅ | 见本文件 |
| T02 | Capability audit | ✅ | docs/V0_4_ALPHA3_DATA_CAPABILITY_AUDIT.md |
| T09 | /web pending filter tabs | ✅ | 391d59e |
| T11-T15 | /web bulk operations（set_category / set_merchant / confirm_ready / reject / keep_duplicate） | ✅ | 391d59e |
| T17 | Rules Preview API（POST /api/rules/preview） | ✅ | 215cd89 |
| T18 | Rules Apply Pending API（POST /api/rules/apply-pending） | ✅ | 215cd89 |
| T19 | /web Rules 页（CRUD / preview / apply-pending） | ✅ | 1d3f452 |
| T24 | Recurring Candidates API（GET /api/insights/recurring-candidates） | ✅ | 215cd89 |
| T25 | /web Reports 固定支出候选卡片 | ✅ | 1d3f452 |

### 安全不变式回归

- 公网仅 /api/*：✅（/web/* 远程 403 测试通过）
- 不自动确认：✅（confirm_ready 跳过 amount_cents=None；apply-pending 只改 category）
- 不改 schema：✅（CategoryRule / Expense 未变更）
- 无密钥/绝对路径泄漏：✅（	est_alpha3_endpoints_no_secret_leak 通过）
- pytest：237 passed（v0.4-alpha2 基线 212）
- ruff：clean

---

## 10. Slice 2 进度（branch `v0.4-alpha3-slice2-reports-dq-arch`）

> 基线：slice 1 head `080ca29`。slice 2 计划与硬闸门见 `V0_4_ALPHA3_SLICE2_REPORTS_DQ_ARCH.md`，文件大小审计见 `V0_4_ALPHA3_SLICE2_STRUCTURE_AUDIT.md`，最终对账见 `V0_4_ALPHA3_SLICE2_CODE_DOC_TEST_RECONCILIATION.md`。

### Slice 2 收口（2026-05-11，head `3598904`，PR #14 CI 双绿）

| 模块 | 状态 | 关键 commit |
|------|------|------|
| M0 结构治理 | ✅ | 5be3395 / f0ae048 |
| M1 Android Reports | ✅ | 0f1f476 / 7dbaa06 / aca80cd |
| M2 Monthly Goal | ✅ | 既往 + 0f1f476 (StatsOverviewCard 整合 budgetProgress) |
| M3 Merchant/Category | ✅ | 348d0f0 |
| M4 Data Quality | ✅ | bc43cd9 / 8aebded |
| M5 CSV Export/Import | ✅ | 4b9531a |
| M6 Duplicates | ✅ | 9ee1d8b |
| M7 Android Review 快速操作 | ⚠️ 部分（4 BottomSheet 延期，记录于 RUNBOOK §10） | — |
| M8 Owner Console + Windows Tasks | ✅ | 3e08bdc / 9c82d30 / 84eca17 |
| M9 Docs / Screenshot / Runbook | ✅ | bdb8853 / 7f84c17 / a708b85 / 3598904 |

**测试基线：237 → 292 passed**（slice 2 净增 55 个测试）。ruff/compileall/smoke 全绿，verify_project ✅。

### G2 文件大小阈值合规

| 文件 | 行数 | 阈值 | 状态 |
|---|---:|---:|---|
| `app/routes/web_app.py` | 231 | 280 | ✅ |
| `app/routes/web_common.py` | 196 | 280 | ✅ |
| `app/routes/web_pending.py` | 234 | 280 | ✅ |
| `app/routes/web_stats.py` | 101 | 280 | ✅ |
| `app/routes/web_rules.py` | 173 | 280 | ✅ |
| `app/routes/web_data_quality.py` | 42 | 280 | ✅ |
| `app/services/data_quality_service.py` | 140 | 360 | ✅ |
| `app/static/web/web.css` | 278 | 500 | ✅ |
| `app/templates/web/data_quality.html` | 90 | 220 | ✅ |

### 兼容性保证

- `tests/test_web_app.py` 仍 `from app.routes.web_app import _require_local`：通过 `__all__` 显式 re-export 维护，44 测试零回归。
- 数据库 schema 未变更（slice 2 全部新增能力都基于现有 Expense 表）。
- `/web /owner` 公网仍 403；`/api/insights/data-quality` 走 `get_current_app_context`。

### 推迟到 slice 2 后续 PR（同 branch / 新 commit 即可）

- **M1 Android Reports Engine**（T05-T11）：StatsScreen.kt（844 行）→ ui/screens/stats/ 子包 + 8 张新卡片
- **M2 Monthly Goal MVP**（T12-T14）：/api/goal/monthly + /web 编辑页 + Android 卡片
- **M3 Merchant / Category 治理**（T15-T18）：merchant_service / 商家归一 / 分类管理
- **M5 CSV Export / Import**（T22-T23）
- **M6 Duplicates 工作台**（T24-T25）：/web/duplicates 页
- **M7 Android Review 快速操作**（T26-T29）
- **M8 Owner Console 产品化**（T30-T32）：owner.css token 提取 / 备份按钮重排
- **M9 文档 / 截图 / 验收**（T34-T36）

理由：M0（结构治理）+ M4（数据质量）已经构成 slice 2 的 **可独立发布的工程加固切片**：把 832 行 web_app.py 拆成 ≤ 280 的 6 个模块、补齐 G2 闸门、并交付了数据体检 dashboard 的端到端通路（service / API / /web / CSS / 测试）。剩余 Android UI + 治理工作量大，独立 commit 持续推送、不阻塞当前结构加固的合入。

### 推迟到下一个 PR

下列任务保留待 alpha3 后续 PR 完成（独立可发布，互不依赖）：

- **PR A 续**：T03-T08 Android Reports 新卡片（分类排行 / 商家排行 / 7 天趋势 / 最大一笔 / 待确认概况）、T28-T29 Android 本月目标卡片
- **PR C 续**：T20 Android Settings 规则只读入口、T21-T23 商家归一 / 别名 / 分类管理
- **PR D**：T26 Android 固定支出候选卡片、T27/T30 Goal MVP /web 编辑、T31-T33 CSV 导出 / 导入 MVP / /web duplicates 页
- **PR E**：T34 /web Data Quality Dashboard、T35-T38 Android Review 增强、T39-T41 Owner 产品化、T42-T45 文档 / 截屏 / Runbook / 全验证

理由：本次会话聚焦于 **后端 + /web Review 工作台 + 规则引擎 + 固定支出洞察**，构成一个可以独立闭环验证的功能切片；Android UI 改造与 CSV/Owner polish 不依赖本切片，独立 PR 风险更小、回滚更轻。
