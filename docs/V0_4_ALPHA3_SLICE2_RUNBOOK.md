# v0.4-alpha3 slice 2 — 日常运维 Runbook

> 适用范围：`v0.4-alpha3-slice2-reports-dq-arch` 及之后版本。
> 阅读对象：本机 owner（同时也是开发者）。
> 公网仍仅暴露 `/api/*`，`/web`、`/owner` 任何时候只能在本机 loopback 访问。

## 1. 启动 / 停机

```powershell
# 启动后端（前台，观察日志）
cd e:\projects\xiaopiaojia\backend
.\run.bat

# 停机：Ctrl+C；或在另一终端
Get-Process python | Where-Object { $_.Path -like "*xiaopiaojia*" } | Stop-Process
```

Cloudflare Tunnel / Windows 计划任务化的完整流程参见
[`docs/WINDOWS_SERVICE_RUNBOOK.md`](WINDOWS_SERVICE_RUNBOOK.md)
与 [`docs/CLOUDFLARE_TUNNEL.md`](CLOUDFLARE_TUNNEL.md)。

## 2. Owner Console 首页（`/owner`）

打开 `http://127.0.0.1:8000/owner`，slice 2 起新增 **运营快照** 卡片：

| 指标 | 含义 | 入口 |
| ---- | ---- | ---- |
| 待确认 | `expense.status = 'pending'` 总数 | `/web/pending` |
| 可一键入账 | 有金额 + 有商家 + 非疑似重复 | `/web/pending` |
| 疑似重复 | `duplicate_status = 'suspected'` | `/web/duplicates` |
| 缺商家 | merchant 为空/null | `/web/data-quality` |
| 未分类 | category 空 / "未分类" | `/web/categories/uncategorized` |
| 最久未处理 | 最早 pending 距今天数 | `/web/pending` |

下方快捷链接直接跳到对应 `/web` 工作台。

## 3. iPhone 上传链接

1. `/owner/upload-links` → 新建一条，**一次性**复制完整 `/u/<key>` URL。
2. 在 iPhone「Shortcuts」用 `POST /u/<key>` + `image/png`。
3. 旋转 / 撤销同样在该页面，旋转后旧 key 立即失效。

## 4. 日常 pending 处理（建议顺序）

每天处理一次：

1. **数据体检** `/web/data-quality`
   - 看 `pending_total / ready_to_confirm`；若 `ready_to_confirm > 0` 走步骤 2。
2. **重复整理** `/web/duplicates`
   - 「保留两条」清除疑似标记；「删除当前」/「删除被复制的」二选一。
3. **未分类** `/web/categories/uncategorized`
   - 勾选多条 + 选分类 + 「批量设置」。
4. **待确认** `/web/pending`
   - 单条编辑或一键入账。
5. **本月统计** Android `Reports` Tab（月度目标卡 + 7 天趋势 + 分类条）。

## 5. CSV 导入 / 导出

- 导出：`/web/export.csv?ledger_id=<ledger>`（自动 UTF-8 BOM，Excel 直接可读）。
- 导入：`/web/import` → 上传 CSV → 预览（前 500 行）→ 确认入库。
  - 必填列：`amount_yuan` 或 `amount_cents`
  - 可选列：`merchant / category / note / expense_time / tags / source`
  - 编码自动尝试 UTF-8 → GB18030；BOM 自动剔除。
  - 单文件 ≤ 1 MiB；无效行跳过、其余成功插入。

## 6. 备份

- `/owner/backups` 触发 SQLite 离线快照；保留窗口由 `backups/` 目录策略控制。
- 长期备份建议在 NAS 上做日级 rsync，不放公网。

## 7. 故障速查

| 现象 | 检查 |
| ---- | ---- |
| iPhone 上传 401 | upload link 已撤销或被轮换 |
| `/web/*` 返回 403 | 用了非 loopback Host（Cloudflare Tunnel 也会被拒） |
| `/api/health` 502 | 后端没启动 / 端口被占用 |
| 导入预览乱码 | 文件非 UTF-8/GB18030，先用 Excel 另存为 UTF-8 |
| Android 报表空 | 该月无 confirmed；先确认账单后再看 |

## 8. 验证脚本

```powershell
cd e:\projects\xiaopiaojia
.\scripts\verify_project.ps1
```

应输出 pytest 全绿 + ruff 0 issue + git diff --check 干净。

## 9. 截图工件

slice 2 验收的核心 UI 截图集中在 `artifacts/screenshots/`（该目录受 `.gitignore`
管控，只在本机存档）。一键重新生成：

```powershell
cd e:\projects\xiaopiaojia
pwsh -ExecutionPolicy Bypass -File scripts\capture_slice2_screenshots.ps1
```

该脚本会在 `127.0.0.1:8765` 临时拉起一个 uvicorn 实例（通过
`XPJ_EXTRA_LOOPBACK_HOSTS` 把该端口纳入 loopback 白名单），用 Edge
headless 抓取以下页面，结束后自动停掉 uvicorn：

- `/owner` — 运营快照卡
- `/web` — 仪表盘
- `/web/pending` — 待确认列表
- `/web/data-quality` — 数据体检
- `/web/duplicates` — 重复整理（双列）
- `/web/categories` — 分类聚合
- `/web/categories/uncategorized` — 未分类批量
- `/web/import` — CSV 导入向导
- `/web/stats` — 报表

## 10. 未完成事项（待后续 PR）

> slice 2 合同内但因预算未交付的条目，本节做"已落地"标记，避免后续 PR 重复领取。

### PR18 T19-T23 — Android 评审快速操作 BottomSheet ✅ 已在 slice 3 交付

| 编号 | 功能 | 实际落地文件 |
|------|------|-------------------|
| T19 | 快速设置分类 (`QuickCategorySheet`) | `android/app/src/main/java/com/ticketbox/ui/screens/pending/sheets/QuickCategorySheet.kt` |
| T20 | 快速设置商家 (`QuickMerchantSheet`) | `android/app/src/main/java/com/ticketbox/ui/screens/pending/sheets/QuickMerchantSheet.kt` |
| T21 | 补填金额流程 (`MissingAmountSheet`) | `android/app/src/main/java/com/ticketbox/ui/screens/pending/sheets/MissingAmountSheet.kt` |
| T22 | 批量确认 (`BulkConfirmSheet`) | `android/app/src/main/java/com/ticketbox/ui/screens/pending/sheets/BulkConfirmSheet.kt` |
| T22b | 疑似重复确认 (`DuplicateConfirmSheet`) | `android/app/src/main/java/com/ticketbox/ui/screens/pending/sheets/DuplicateConfirmSheet.kt` |
| T23 | ViewModel 评审动作扩展 | `viewmodel/PendingViewModel.kt` + `viewmodel/PendingViewModelReviewActions.kt` |

完整设计 / 验收口径参见 [`V0_4_ALPHA3_SLICE3_ANDROID_REVIEW_WORKFLOW.md`](V0_4_ALPHA3_SLICE3_ANDROID_REVIEW_WORKFLOW.md)，PR 入口 [#15](https://github.com/zhe9898/7/pull/15)。

slice 3 同步把 `PendingScreen.kt` 拆为：

- `ui/screens/PendingScreen.kt`（slim orchestrator，≤ 280 行）
- `ui/screens/pending/PendingReviewSheetHost.kt`
- `ui/screens/pending/PendingHeader.kt` / `PendingFilters.kt` / `PendingComponents.kt` / `PendingEmptyStates.kt`

架构门以 G2 标准对齐（Compose Screen ≤ 280、BottomSheet ≤ 220、ViewModel ≤ 360），所有新增文件均通过 `:app:testGrayDebugUnitTest` / `:app:lintGrayDebug` / `:app:assembleGrayDebug` 验证。
