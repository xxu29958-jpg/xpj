# v0.8.0a1 Budget 收口报告

日期：2026-05-14
分支：`codex/v0.8-budget-dashboard`
阶段：Budget / 月度可花三端基线

## 结论

v0.8.0a1 已完成服务端预算基线、Android 预算页、统计页预算卡、`/web` 预算 Dashboard、`/owner` 只读预算状态卡，并完成临时后端 + 已绑定真机走查。当前状态可以进入 v0.8 RC 判定；RC 前不再扩大预算模型范围。

## 本轮新增收口

- Android 角色写权限默认值修正：只有明确的 `owner` / `member` 才允许本地写入口；`viewer`、空角色和未知角色全部按只读处理。
- 补齐 v0.8 预算截图基线：Android owner、Android viewer 只读、Android stats 预算卡、`/web/budgets`、`/owner` 预算状态。
- 使用临时 SQLite 和临时 uploads 完成已绑定真机走查，不污染长期开发库。

## 已验证能力

| 能力 | 结果 |
|---|---|
| 月度总预算 | Android / `/web` / `/owner` 均显示预算状态。 |
| Flex Budget 简化版 | 固定支出、非月度预留、结转参与预算计算。 |
| 分类预算 | Android 和 `/web` 显示分类预算执行。 |
| 排除分类 | 投资、转账不计入预算已花，仍在排除项中展示。 |
| viewer 只读 | Android viewer 预算页可读、不可保存；后端仍以 `permission_denied` 作为最终边界。 |
| 统计页预算卡 | Android 统计页优先显示服务端预算卡。 |
| Owner Console | `/owner` 只读展示预算状态，不提供预算写操作。 |

截图索引见 `docs/V0_8_BUDGET_SCREENSHOTS.md`，原始截图和日志在 `artifacts/v0_8_budget/`（不入仓）。

## 验收数据

临时后端：`127.0.0.1:18765`
临时库：`artifacts/v0_8_budget_qa_20260514-084906/ticketbox.db`

关键预算结果：

| 字段 | 值 |
|---|---:|
| 月度总预算 | ¥5,000.00 |
| 结转后总额 | ¥5,120.00 |
| 固定支出 | ¥1,880.00 |
| 非月度预留 | ¥600.00 |
| Flex 可花 | ¥2,640.00 |
| 已花（不含排除分类） | ¥440.40 |
| 剩余可花 | ¥4,679.60 |
| 排除金额 | ¥1,800.00 |

## 回滚与兼容

- 数据模型只新增预算表；预算只提供提示和 Dashboard 数据，不阻断上传、手动记账、确认、规则应用或导出。
- Android 仍以后端为最终权限边界；本轮只是把本地未知角色改为保守只读，避免 UI 在 role 未刷新时先打开写入口。
- 旧本机 `monthlyBudgetCents` 不再作为 v0.8 服务端预算来源；统计页有服务端预算仓库时优先使用服务端预算。

## 验证命令

本轮已执行：

```powershell
cd E:\projects\xiaopiaojia\android
.\gradlew.bat --no-daemon :app:installInternalDebug
.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest --tests com.ticketbox.domain.model.LedgerRolesTest --tests "*Budget*"
.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
.\gradlew.bat --no-daemon :app:assembleGrayDebug
```

真机验证：

```powershell
adb -s c16cd054 reverse tcp:18765 tcp:18765
adb -s c16cd054 shell am start -n com.ticketbox.internal/com.ticketbox.MainActivity `
  -e ticketbox.debug.server_url http://127.0.0.1:18765 `
  -e ticketbox.debug.session_token <redacted>
```

截图和 UI tree 见 `artifacts/v0_8_budget/`。

仓库检查：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
git diff --check
```

## 剩余风险

- 本轮真机走查使用 internal debug + 临时后端；gray 包生产域名的完整长期使用回归仍放到 RC。
- 本轮没有把 v0.8 扩展到通知推送提醒；超支提醒仍是后续切片，不阻塞当前预算 Dashboard 基线。
- 原始截图和日志不入仓，报告只保留索引和关键结果。
