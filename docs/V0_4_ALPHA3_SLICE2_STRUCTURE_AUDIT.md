# Structure Audit — v0.4-alpha3 slice 2

> 截止 `080ca29`（slice 1 head）。阈值见 `V0_4_ALPHA3_SLICE2_REPORTS_DQ_ARCH.md` §G2。

## 1. 阈值

| 类别 | 阈值（行） |
|---|---|
| Python route 单文件 | 280 |
| Python service 单文件 | 360 |
| Jinja template | 220 |
| CSS 单文件 | 500 |
| Compose Screen | 450 |
| ViewModel | 350 |
| Repository | 420 |
| 测试单文件 | 600 |

## 2. 文件体检（按维度）

### 后端 routes

| 文件 | 行数 | 状态 | 处置 |
|---|---:|---|---|
| `app/routes/web_app.py` | **832** | **超 3×** | **本轮必须拆** |
| `app/routes/owner_console.py` | 515 | 超 1.8× | 暂缓（slice 2 不直接扩） |
| `app/routes/uploads.py` | 231 | OK | — |
| `app/routes/expenses.py` | 206 | OK | — |
| 其余 routes | < 200 | OK | — |

### 后端 services

| 文件 | 行数 | 状态 | 处置 |
|---|---:|---|---|
| `services/identity_service.py` | 524 | 超 | 暂缓（边界服务，slice 2 不扩） |
| `services/expense_service.py` | 404 | 超 | 暂缓（核心 CRUD，slice 2 仅复用） |
| `services/receipt_parse_*` | 144-426 | 多文件 | OK（已按 5 个解析器拆开） |
| `services/identity_service.py` | 524 | 超 | 暂缓 |
| `services/ocr_service.py` | 426 | 超 | 暂缓（外部 OCR 隔离） |
| `services/stats_service.py` | 294 | OK | 新增 stats report 用其上层 helper |
| `services/classify_service.py` | 287 | OK | — |
| 其余 services | < 290 | OK | — |

### 后端模板

| 文件 | 行数 | 状态 |
|---|---:|---|
| `templates/web/pending.html` | 139 | OK |
| `templates/web/stats.html` | 137 | OK |
| `templates/web/rules.html` | 121 | OK |
| 其余 | < 100 | OK |

### CSS

| 文件 | 行数 | 状态 |
|---|---:|---|
| `static/web/web.css` | 264 | OK（slice 2 末预计 +120） |
| `static/owner/owner.css` | 251 | OK |

### Android UI

| 文件 | 行数 | 状态 | 处置 |
|---|---:|---|---|
| `ui/screens/StatsScreen.kt` | **844** | **超 1.9×** | **本轮必须拆**（slice 2 还要加 7 张报表卡） |
| `ui/screens/LedgerScreen.kt` | 765 | 超 | 暂缓（slice 2 不扩） |
| `ui/screens/PendingScreen.kt` | 725 | 超 | 暂缓 → T26/T27 时再判断 |
| `ui/screens/ExpenseEditScreen.kt` | 659 | 超 | 暂缓 |
| `ui/screens/LedgerManualExpenseSheet.kt` | 294 | OK | — |
| `ui/screens/SettingsScreen.kt` | 232 | OK | — |
| 其余 | < 120 | OK | — |

### 测试

| 文件 | 行数 | 状态 | 处置 |
|---|---:|---|---|
| `tests/test_expenses.py` | **911** | **超 1.5×** | 暂缓（slice 2 不直接扩，新增测试落到专门文件） |
| `tests/test_tenant_isolation.py` | 586 | 接近 | OK |
| `tests/test_web_app.py` | 476 | OK | slice 2 新页面用新文件（test_web_data_quality.py 等） |
| `tests/test_owner_console.py` | 443 | OK | — |
| 其余 | < 400 | OK | — |

## 3. 本轮必须先拆

1. **`app/routes/web_app.py` (832 → 实际拆 5 个文件，全部 ≤ 280)** ✅ T03 完成
   - 实际产物（与原计划相比简化为同级 5 个模块，避免引入新包路径以降低 import 风险）：
     - `web_common.py` (196 行) — `_require_local`, `LocalOnly`, `_resolve_selected_ledger_id`, `_list_ledger_options`, `_with_ledger`, `_base_ctx`, `LedgerOption`, `_expense_view`, `_amount_yuan`, `_SOURCE_LABELS`, `_dashboard_cards`, `templates`
     - `web_app.py` (231 行) — dashboard + slash redirect + confirmed + edit/save/confirm/reject + image/thumbnail；显式 `__all__ = ["router", "_require_local", "templates"]` 兼容现有测试
     - `web_pending.py` (234 行) — `GET /web/pending`、`POST /web/review/bulk` + `_BULK_ACTIONS`
     - `web_stats.py` (101 行) — `GET /web/stats`
     - `web_rules.py` (173 行) — 5 个 rules 路由（list / create / toggle / delete / apply-pending）
   - `main.py` 注册 4 个 `APIRouter`，全部 `prefix="/web"`。
   - 验证：237 passed in 219.9s（与拆分前完全一致），ruff clean。
   - 兼容性：`tests/test_web_app.py` 依旧 `from app.routes.web_app import _require_local as _web_require_local` 并 override，44 通过。

2. **`ui/screens/StatsScreen.kt` (844 → 目标 ≤ 450)**
   - 新建 `ui/screens/stats/` 子包：
     - `StatsScreen.kt`（瘦版，仅 Scaffold + LaunchedEffect + 子组件挂载）
     - `StatsSummarySection.kt`
     - `StatsCategoryBreakdownCard.kt`（已存在的分类卡）
     - `StatsLifestyleCard.kt`（已存在的最大一笔等）
     - `StatsMonthComparisonCard.kt`（已存在的对比）
   - slice 2 新增也都放在此目录：
     - `CategoryRankingCard.kt`
     - `MerchantRankingCard.kt`
     - `DailyTrendCard.kt`
     - `MaxExpenseCard.kt`
     - `PendingOverviewCard.kt`
     - `RecurringCandidatesCard.kt`
     - `MonthlyGoalCard.kt`

## 4. 本轮暂缓（不阻塞 slice 2）

- `owner_console.py` 515：slice 2 仅在该文件加 1-2 个统计读取，不会让它过 600。Owner Console 拆分作为下一版（v0.4-beta1 候选）的结构治理任务。
- `expense_service.py` 404：核心 CRUD，slice 2 只复用、不扩展，强行拆会破坏 slice 1 的稳定性。
- `identity_service.py` 524 / `ocr_service.py` 426：边界服务，不在 slice 2 路径上。
- `LedgerScreen.kt` / `PendingScreen.kt` / `ExpenseEditScreen.kt`：T26/T27 仅在 PendingScreen 加 chip + bottom sheet；如果会让文件继续涨，会在那一步拆出 `pending/` 子包。
- `tests/test_expenses.py` 911：新增 slice 2 测试一律落到新文件（`test_data_quality.py`、`test_web_data_quality.py`、`test_csv_export.py` 等），不再往 `test_expenses.py` 塞。

## 5. 决策原则

> 阈值不是机械砍数字。规则是：**超过阈值的文件，不能继续往里塞新功能；要塞之前必须先拆出清楚模块。**

slice 2 必须先完成 §3 的两个拆分，再进入 M1+ 功能任务。
