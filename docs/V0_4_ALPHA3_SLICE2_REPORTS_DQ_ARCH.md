# v0.4-alpha3 slice 2 — Reports / Data Quality / Architecture Hardening

> 基线：PR #13 head `080ca29`（branch `v0.4-alpha3-smart-ledger-engine`，open / mergeable=true，未合并）
> Slice 2 branch：`v0.4-alpha3-slice2-reports-dq-arch`
> Slice 2 PR：**#14 open / draft / mergeable=true，head `3598904`（**Backend CI ✅ Android CI ✅**）**
> 上游 PR #12 仍 open，slice 1 → slice 2 链路均不依赖 PR #12 合入。

## 0. 完成状态总览（2026-05-11 收口）

| 模块 | 状态 | 关键交付 | 测试 |
|------|------|----------|------|
| M0 结构治理 | ✅ 完成 | web_app.py 198 行 + 8 个 web_* 子模块（最大 209 行） | 老测试兼容 |
| M1 Android Reports Engine | ✅ 完成 | StatsScreen 137 行 + stats/ 8 张卡片（≤ 198 行/卡） | 既有 Compose UI 测试 |
| M2 Monthly Goal MVP | ✅ 完成 | StatsViewModel 内嵌 budgetProgress + Settings 入口 | 见 SettingsViewModel/StatsViewModel 单测 |
| M3 Merchant / Category 治理 | ✅ 完成 | merchant_service.normalize_merchant + /web/categories + /web/categories/uncategorized | +9 测试 |
| M4 Data Quality Dashboard | ✅ 完成 | data_quality_service tenant-scoped + /api/insights/data-quality + /web/data-quality | +10 测试 |
| M5 CSV Export / Import | ✅ 完成 | /web/export.csv（ledger+month+category 过滤）+ /web/import 两步预览 | +11 测试 |
| M6 Duplicates 工作台 | ✅ 完成 | /web/duplicates 双列卡 + 三处置动作（保留/删当前/删原始） | +8 测试 |
| M7 Android Review 快速操作 | ⚠️ 部分 | Needs-Review 筛选器 + markNotDuplicate 已就绪；四套 BottomSheet 延期 | — |
| M8 Owner Console 产品化 | ✅ 完成 | 运营快照 + 账本健康卡（per-ledger DQ） + Windows 任务只读状态 | +12 测试 |
| M9 Docs / Screenshot / Runbook | ✅ 完成 | RUNBOOK 113 行 + capture_slice2_screenshots.ps1（XPJ_EXTRA_LOOPBACK_HOSTS） | — |

**测试基线：237 → 292 passed（ruff/compileall/smoke 全绿，verify_project ✅，CI 双绿）**

### 部分完成与延期

- **M7 T19-T23**：Android 评审快速操作 BottomSheet 四件套（QuickCategory / QuickMerchant / MissingAmount / BulkConfirm）延期到 v0.4-alpha3-slice3 或 v0.5。理由：本 PR 已 27 commits / 80 changed files / +7912 / -1128，继续扩 Android 屏幕实现会越线 G2 大文件门（PendingScreen.kt 已 693 行）。基础设施齐备（ModalBottomSheet import + NeedsReviewFilter.Duplicate + markNotDuplicate ViewModel + ExpenseCard onKeepDuplicate），下一轮可直接接续。详见 `V0_4_ALPHA3_SLICE2_RUNBOOK.md §10`。

### 已知 P2（不阻塞 ready）

- CSV `/web/export.csv` 当前仅支持 ledger/month/category 过滤，未实现 merchant/status 筛选（status 由 export_confirmed_csv 名称隐含为 confirmed）。
- ExpenseEditScreen.kt / LedgerScreen.kt / PendingScreen.kt 既已 > 450 行，但均为 slice 2 之前的历史债，本轮不触碰。
- ExpenseRepository.kt 516 行 > 420 阈值（slice 2 内扩展）：已记录于 SLICE2_STRUCTURE_AUDIT，留下一轮处理。
- artifacts/screenshots/ 截图由 `scripts\capture_slice2_screenshots.ps1` 生成，不入仓。

## 1. 一句话目标

把 Smart Ledger Engine 从 /web 规则整理推进到 **Android 报表 / 数据质量 / 商家分类治理 / 导入导出 / Owner 产品化**，
同时把代码结构压住，避免 route / Screen / 测试文件继续膨胀成维护债。

## 2. 不做清单（继承 slice 1，并加固）

- 不做家庭成员 / 多账号（→ v0.5）
- 不做完整 Recurring 表 / 自动入账（仍只做候选）
- 不做分类预算 / rollover 预算 / 通知
- 不做 Schema 破坏性迁移（CategoryRule / Expense / Setting 表均维持现状）
- 不引入 chart 库（7 天趋势 Compose Canvas / Row bars 原生绘制）
- 不引入重型数据框架做 CSV
- 不引入 alpha / beta / RC / 停更依赖
- 不自动确认任何账单
- 不自动改写已确认账单

## 3. 工程硬闸门（G1-G5，强制）

参见任务合同 §四：

- **G1 强代码**：业务逻辑禁止堆在 route / Composable / template
- **G2 大文件规范**：超阈值文件必须先拆才能塞功能（见 `V0_4_ALPHA3_SLICE2_STRUCTURE_AUDIT.md`）
- **G3 结构边界**：routes → services → models；UI → ViewModel → Repository → ApiService/Dao
- **G4 依赖规范**：默认不新增；如需新增必须写 `docs/DECISIONS/00xx-*.md`
- **G5 测试不降级**：每个功能任务有空状态 + 异常 + ledger 隔离测试

## 4. 范围（slice 2 = 9 模块）

```
M0 结构体检与架构梳理          T01-T04
M1 Android Reports Engine     T05-T11
M2 Monthly Goal MVP           T12-T14
M3 Merchant / Category 治理   T15-T18
M4 Data Quality Dashboard     T19-T21
M5 CSV Export / Import        T22-T23
M6 Duplicates 工作台          T24-T25
M7 Android Review 快速操作    T26-T29
M8 Owner Console 产品化       T30-T32
M9 文档 / 截图 / 验收         T33-T36
```

执行顺序：先 Phase 0 结构治理，再按 P0 → P1 → P2 推进。具体优先级与完成报告格式见任务合同（user request §六/§九）。

## 5. 安全不变式（继承）

- 公网仍仅 `/api/*`，`/web /owner` 公网继续 403
- 所有新增 API 必须经过 `get_current_app_context` 或 loopback gate
- 所有新增 service 必须按 `tenant_id` 隔离
- `LedgerRepository.switchLedger` / `ExpenseDao.findAnyByServerIds` 不被触碰
- 无 token_hash / upload_key / 绝对路径泄漏
- 无 Schema 破坏性迁移

## 6. 测试矩阵

后端：`compileall` + `ruff` + `pytest` + `smoke_test.py`
Android：`testGrayDebugUnitTest` + `assembleGrayDebug` + `assembleInternalDebug` + `lintGrayDebug`
全量：`scripts\verify_project.ps1` + `git diff --check` + `scripts\check_text_encoding.ps1`

## 7. 回滚

`git revert` 单次即可；分支与 PR #13 独立。
