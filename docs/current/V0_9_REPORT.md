# v0.9.0a1 Reports / Goals 收口报告

日期：2026-05-14

## 版本定位

v0.9 把 v0.8 的预算和月度可花基线推进到可视化报表层：服务端提供结构化 Reports、Goals 和 Dashboard 卡片偏好；Android 与本机 `/web` 负责展示层图表；`/owner` 只做运维视角的视觉一致性收口。核心闭环仍然是截图上传、OCR/规则生成草稿、人工确认入账。

本版本不改变 `identity_schema=v0.3`，不改变金额、时间、账本隔离、图片保护或 viewer 只读契约。

## 已完成范围

- 后端 Reports：`GET /api/reports/overview` 与 `GET /api/reports/overview.csv`，按当前账本、confirmed 状态和 `expense_time` fallback `confirmed_at` 聚合趋势、商家排行和分类环比。
- 后端 Goals：第一刀支持 `spending_limit + monthly`，包含创建、列表、详情、更新、归档和按月进度计算；viewer 可读，owner/member 可写。
- 后端 Dashboard Cards：Android 与 `/web` 分 surface 保存卡片顺序和显隐；viewer 可读，owner/member 可写。
- Android：统计页接入服务端 Reports、Goals 和 Dashboard 卡片偏好，并按 ADR 引入 Vico 3.1.0 作为 Compose 展示层图表库。
- `/web`：Reports 页面接入自托管 ECharts 6.0.0，不使用 CDN；保留服务端渲染回退；CSV 导出仍走结构化数据。
- `/owner`：继续保持 loopback 运维定位，版本、状态和视觉 token 跟随三端收口。
- 文档：API、图表库政策、Android Vico ADR、`/web` ECharts ADR、设计 token 和功能表已同步。

## 明确延期

- Goals 只实现月度支出上限，不实现储蓄目标、资产目标或自动入账。
- Android 本版提供 Goals 摘要和空状态，不提供完整移动端 Goals 新建、编辑、归档 UI；这些操作当前以后端 API 和 `/web` 为主。
- Dashboard Cards 只支持 `android` 和 `web` surface；`/owner` 仍使用固定运维卡片，不保存普通用户式卡片偏好。
- PNG 导出由展示层完成；后端不渲染图表图片，不返回 ECharts 或 Vico 私有格式。
- 大 CSV、商品级 OCR、家庭拆账和 v0.x -> v1.0 迁移工具进入 v1.0 后端主线。

## 代表性验证

已执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
git diff --check
Set-Location backend; .\.venv\Scripts\python.exe -m compileall app scripts tests
Set-Location backend; .\.venv\Scripts\ruff.exe check app scripts tests
Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests\test_auth_bootstrap.py tests\test_reports.py tests\test_goals.py tests\test_dashboard_cards.py tests\test_web_reports_goals.py
Set-Location backend; .\.venv\Scripts\python.exe scripts\smoke_test.py
powershell -ExecutionPolicy Bypass -File scripts\check_dependency_versions.ps1
Set-Location android; $env:JAVA_TOOL_OPTIONS='-Xshare:off'; .\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests\test_reports.py tests\test_goals.py tests\test_dashboard_cards.py tests\test_v09_reports_goals_integration.py tests\test_database_migration.py tests\test_ledger_query_scope_guard.py tests\test_web_reports_goals.py tests\test_web_dashboard_cards.py
Set-Location android; $env:JAVA_TOOL_OPTIONS='-Xshare:off'; .\gradlew.bat --no-daemon :app:assembleGrayDebug :app:assembleInternalDebug
Set-Location android; $env:JAVA_TOOL_OPTIONS='-Xshare:off'; .\gradlew.bat --no-daemon :app:lintGrayDebug
Set-Location android; $env:JAVA_TOOL_OPTIONS='-Xshare:off'; .\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
```

结果：后端 v0.9 重点套件 34 passed；Android `testGrayDebugUnitTest`、`assembleGrayDebug`、`assembleInternalDebug`、`lintGrayDebug` 均 BUILD SUCCESSFUL。

## 风险和处理

- 本机 Kimi JDK 的 CDS 共享归档会向 `java -version` 输出 warning，污染 Gradle JDK image transform 的版本解析；当前验证使用 `JAVA_TOOL_OPTIONS=-Xshare:off` 关闭共享归档。
- 依赖审计提示 Compose BOM、coroutines、AGP、KSP、Pydantic 和 python-multipart 有稳定小版本更新；v0.9 收口不顺手升级依赖，避免把发布门禁变成依赖迁移。
- Android Goals 管理 UI 没进入本版完整范围；进入 v1.0 前如果要把 Goals 做成日常主流程，需要另补移动端创建/编辑/归档入口和真机截图验收。
