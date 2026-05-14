# v0.8 Budget 截图与产物索引

所有原始截图和日志存放在 `artifacts/v0_8_budget/`，该目录被 `.gitignore` 排除，不入仓。本索引只记录文件清单、页面和验收含义。

## Android 真机

设备：Xiaomi 2410DPN6CC，Android 16，adb id `c16cd054`。
包：`com.ticketbox.internal`，通过 internal debug intent 绑定临时本地后端 `127.0.0.1:18765`。

| 文件 | 说明 |
|---|---|
| `android_budget_owner.png` | owner 角色预算页：显示 `2026-05`、月度总预算、剩余可花、已花、Flex 可花、固定支出和排除金额。 |
| `android_budget_owner.xml` | owner 角色预算页 uiautomator dump。 |
| `android_stats_budget.png` | 统计页预算卡：显示“月度预算 / 还可花 ¥4,679.60 / 8%”。 |
| `android_stats_budget.xml` | 统计页 uiautomator dump。 |
| `android_budget_viewer_readonly.png` | viewer 角色预算页：预算数据可读，预算设置只显示“当前角色为只读，无法修改账本。”，不显示“保存预算”。 |
| `android_budget_viewer_readonly.xml` | viewer 角色预算页 uiautomator dump。 |
| `real_device_budget_logcat.txt` | 真机走查 logcat，临时 session token 已打码。 |

## Web / Owner

| 文件 | 说明 |
|---|---|
| `web_budget_dashboard.png` | `/web/budgets?month=2026-05`：月度预算、剩余、固定支出、Flex、排除分类和分类预算执行。 |
| `owner_budget_status.png` | `/owner`：只读预算状态卡，显示月度预算、已花、剩余、预算进度和分类超支数。 |

## 临时后端数据

本轮验收使用 `artifacts/v0_8_budget_qa_20260514-084906/` 下的临时 SQLite 和 uploads 目录，不写入长期开发库或生产库。

验收样本：

| 类型 | 金额 |
|---|---:|
| 月度总预算 | ¥5,000.00 |
| 结转 | ¥120.00 |
| 固定支出 | ¥1,880.00 |
| 非月度预留 | ¥600.00 |
| 已花（不含排除分类） | ¥440.40 |
| 排除分类 | 投资 ¥1,000.00；转账 ¥800.00 |
