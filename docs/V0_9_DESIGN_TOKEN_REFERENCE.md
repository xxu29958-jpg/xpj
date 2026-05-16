# v0.9 设计 Token 参考

配合 [v0.9 设计包功能表](V0_9_DESIGN_FUNCTION_TABLE.md) 使用。本文是三端（Android / `/web` / `/owner`）token 的真值表。**v0.9 UI/UX 套图主题包**的视觉系统在这里集中维护：先有 token，再有页面。

## 1. 维护规则

- 三端 token 名按相同语义对应。Android 端用 sibling data class（`ThemeVisuals` / `StateTokens` / `ChartTokens` / `GoalTokens` / `DashboardCardTokens`）；Web / Owner 用 `backend/app/static/shared/tokens.css` 的 CSS 变量。
- **v0.10 主题集**：`paper` 纸本（默认）、`mono` 墨白、`midnight` 玄夜。命名与 `com.ticketbox.domain.model.AppSkin` 保持一致。
- 旧主题（`pine` / `pomelo` / `harbor` / `berry` / `night`）已退役。Android `AppSkin.fromStorageKey()` 把旧 storageKey 自动映射：`pine`/`pomelo`/`harbor` → `paper`、`berry` → `mono`、`night` → `midnight`。CSS 这边没有兼容映射（`data-theme` 仅认新值），但 `_base_ctx` 读 cookie 时只接受 3 个新值，旧 cookie 会被降级到默认 paper。
- Web / Owner 默认 `:root` = `paper`，与 Android `AppSkin.Default` 对齐。`<html data-theme="...">` 由 `_base_ctx` 从 cookie `ui_theme` 读取（`paper` / `mono` / `midnight`）；前端切换由 `desktop.js` 的 `#theme-toggle` 写 cookie + localStorage。
- v0.4 alias shim（`--bg-app` / `--fg-*` / `--chip-*` / `--pill-*`）保留在 `tokens.css` 末尾，直到所有页面消费方迁完到 v0.9 token 名后才能删除。新代码必须直接用 v0.9 名字。
- Android 现有 `ThemeVisuals` 17 字段（被 27 个 UI 文件、60 处消费）**禁止改名 / 禁止删除**。v0.9 仅追加 `surfaceRaised` / `focusRing`，其它新概念走 sibling data class。

## 2. 跨端语义对照

| v0.9 语义 | CSS 变量 | Android（ThemeVisuals 或 sibling） | v0.4 alias（兼容期） |
|---|---|---|---|
| 页面背景 | `--surface-app` | `ThemeVisuals.backgroundTop` | `--bg-app` |
| 卡片底 | `--surface-card` | `ThemeVisuals.solidCard` | `--bg-card` |
| Raised 卡片 | `--surface-raised` | `ThemeVisuals.surfaceRaised`（v0.9 新增） | — |
| 导航条 | `--surface-nav` | （Material 深色背景） | `--bg-nav` |
| 二级面 | `--surface-sunken` | `ThemeVisuals.backgroundBottom` | `--bg-surface-2` |
| 默认文字 | `--text-default` | `MaterialTheme.colorScheme.onBackground` | `--fg-default` |
| 次文字 | `--text-muted` | `MaterialTheme.colorScheme.onSurfaceVariant` | `--fg-muted` |
| Meta 文字 | `--text-meta` | （次次文字，灰蓝） | `--fg-meta` |
| 反白文字 | `--text-on-primary` | `MaterialTheme.colorScheme.onPrimary` | — |
| 主品牌 | `--brand-primary` | `ThemeVisuals.primary` | `--fg-primary` |
| 主品牌强 | `--brand-primary-strong` | `ThemeVisuals.primaryDark` | `--fg-primary-strong` |
| Accent | `--brand-accent` | `ThemeVisuals.accent` | — |
| 焦点环 | `--brand-focus-ring` | `ThemeVisuals.focusRing`（v0.9 新增） | — |
| 成功 bg/fg/border | `--state-success-*` | `StateTokens.success.bg/fg/border` | `--chip-ok-*` / `--fg-success` |
| 警告 bg/fg/border | `--state-warn-*` | `StateTokens.warn.*` | `--chip-warn-*` / `--fg-warn` / `--pill-secondary-*` |
| 危险 bg/fg/border | `--state-danger-*` | `StateTokens.danger.*` | `--fg-danger` |
| 信息 bg/fg/border | `--state-info-*` | `StateTokens.info.*` | `--chip-pending-*` / `--pill-default-*` |
| 中性 bg/fg/border | `--state-neutral-*` | `StateTokens.neutral.*` | `--chip-muted-*` |
| Chart series 1-8 | `--chart-series-1..8` | `ChartTokens.series[0..7]` | — |
| Chart ramp 单色 | `--chart-sequential-from/to` | `ChartTokens.sequentialFrom/To` | — |
| Chart ramp diverging | `--chart-diverging-negative/zero/positive` | `ChartTokens.diverging*` | — |
| 坐标轴 / 标签 | `--chart-axis` / `--chart-axis-label` | `ChartTokens.axis` / `axisLabel` | — |
| 网格 / 强调网格 | `--chart-grid` / `--chart-grid-emphasis` | `ChartTokens.grid` / `gridEmphasis` | — |
| Tooltip bg/fg/border | `--chart-tooltip-*` | `ChartTokens.tooltip*` | — |
| 图例文字 / 标记 | `--chart-legend-fg` / `--chart-legend-marker` | `ChartTokens.legendFg` / `legendMarker` | — |
| Sankey 默认 / 强调 | `--chart-sankey-ribbon` / `-emphasis` | `ChartTokens.sankeyRibbon` / `Emphasis` | — |
| 超支 | `--chart-overspend` | `ChartTokens.overspend` | — |
| 空数据填充 | `--chart-empty` | `ChartTokens.empty` | — |
| Goal idle/onTrack/nearLimit/exceeded/expired | `--goal-{name}-bg/fg/border` | `GoalTokens.{name}` | — |
| Dashboard 卡片 pending/monthSpend/recentUpload/recurring/goals/budget/backup/device | `--card-{name}-accent/icon/surface` | `DashboardCardTokens.{name}` | — |

## 3. 三套主题主体调（v0.10）

| 主题 | brand-primary | accent | surface-app | 适用场景 |
|---|---|---|---|---|
| `paper` 纸本（默认） | `#8a5a2b` 茶铜 | `#d6b487` 奶咖 | `#f3efe6` 米白 | 温润日间、家庭账本默认 |
| `mono` 墨白 | `#0e0e0c` 墨 | `#6f6e6a` 中灰 | `#ededea` 冷灰 | 极简专注、编辑感 |
| `midnight` 玄夜（深色） | `#d6b487` 暖金 | `#8a6a3e` 深铜 | `#0c0d10` 深墨 | 夜班记账、运维 |

`/web` 桌面账本破例引入本地自托管 webfont（Noto Sans SC + Newsreader + Inter），见 `backend/app/static/web/fonts/README.md` 与 `scripts/download-fonts.ps1`。Android 与 `/owner` 仍走系统中文字体栈。

## 4. Chart 调色板说明（P09-12）

每套主题 8 位 series 色板，顺序：

1. 主品牌色
2. Accent（暖金/青绿/木质 等）
3. 主品牌的近邻色（带不同明度）
4. 暖系第三色（区分类目）
5. 冷系第三色
6. 中性偏暖（备用）
7. 中性偏冷（备用）
8. 跨色相补色（最稀有类目）

P09-02 商家排行、P09-03 分类组对比、P09-09 Web Reports 都按这个顺序消费。**超过 8 个类目时由消费页面建立 "Other" 桶，不在 token 层兜底**。

diverging ramp（`--chart-diverging-*`）专给 P09-03 分类组对比的正/负差异。`--chart-overspend` 单独覆盖 series 颜色，用于 P09-12 超支警示。

## 5. Goal 状态映射（P09-04）

| 状态 | 触发条件 | 视觉来源 |
|---|---|---|
| `idle` | 未启用 / 暂停 | 复用 `state-neutral` |
| `onTrack` | 实际值 ≤ 阈值 | 复用 `state-success`，每主题可微调 |
| `nearLimit` | 阈值 < 实际值 ≤ 100% | 复用 `state-warn` |
| `exceeded` | 实际值 > 100% | 复用 `state-danger`，每主题可换语义色（如 Berry 用莓红） |
| `expired` | 周期结束未关闭 | `state-neutral` 减弱 fg alpha |

**不直接 alias 到 state token**——每个主题可以给 Goal 状态做轻量调味（例：Berry 的 exceeded 用 `#7e1f36`，比通用 danger 更深），保持视觉一致性。

## 6. Dashboard 卡片库（P09-05 / P09-10）

8 张卡（与 P09-10 一致）：

| key | 卡片名 | 默认主题（paper） accent |
|---|---|---|
| `pending` | 待确认 | `#8a5a2b` |
| `monthSpend` | 本月支出 | `#1c1a18` |
| `recentUpload` | 最近上传 | `#3e6770` |
| `recurring` | Recurring | `#a4361c` |
| `goals` | Goals | `#4f6b3a` |
| `budget` | 预算 | `#8a5a2b` |
| `backup` | 备份 | `#807968` |
| `device` | 设备 | `#5a4a6e` |

Owner 只在模板里渲染其中的 pending / recurring / budget / backup / device，但 token 在三端都齐全，避免 owner / web 出现颜色对不上的尴尬。

## 7. 文件指引

**Android**：
- 数据类与每主题取值：
  - [ThemeVisuals.kt](../android/app/src/main/java/com/ticketbox/ui/design/ThemeVisuals.kt)
  - [BackgroundVisuals.kt](../android/app/src/main/java/com/ticketbox/ui/design/BackgroundVisuals.kt)
  - [StateTokens.kt](../android/app/src/main/java/com/ticketbox/ui/design/StateTokens.kt)
  - [ChartTokens.kt](../android/app/src/main/java/com/ticketbox/ui/design/ChartTokens.kt)
  - [GoalTokens.kt](../android/app/src/main/java/com/ticketbox/ui/design/GoalTokens.kt)
  - [DashboardCardTokens.kt](../android/app/src/main/java/com/ticketbox/ui/design/DashboardCardTokens.kt)
- 注入入口：[Theme.kt](../android/app/src/main/java/com/ticketbox/ui/theme/Theme.kt) 内 `TicketboxTheme` 的 `CompositionLocalProvider`
- 单元测试：[ThemeVisualsTest.kt](../android/app/src/test/java/com/ticketbox/ui/design/ThemeVisualsTest.kt)

**Web / Owner**：
- 共享 token 真值表：[shared/tokens.css](../backend/app/static/shared/tokens.css)
- Web 入口：[web/web.css](../backend/app/static/web/web.css)（顶部 `@import "../shared/tokens.css"`）
- Owner 入口：[owner/owner.css](../backend/app/static/owner/owner.css)（顶部 `@import "../shared/tokens.css"` + `[data-owner]` 密度覆写）

## 8. 主题切换机制（本轮未启用）

v0.10 base.html 用 `<html data-theme="{{ ui_theme or 'paper' }}">`，由 `_base_ctx` 从 cookie 读取。v0.4 alias shim 仍在 tokens.css 末尾，给 7 个未重写的 legacy `/web` 页面（budgets / goals / categories / rules / merchants / recurring / import / stats / data-quality）兜底。

下一阶段（"appearance only" commit）会做的事：
- Jinja `base.html` 读取 cookie `xpj_theme` 注入 `<html data-theme="{{ theme_key }}">`
- `/web/settings` 和 `/owner/settings` 提供主题选择器
- Owner 额外 set `data-owner` 触发密度覆写
- Android 端 `SettingsAppearance` 与 web/owner 共用 `AppSkin.storageKey`

## 9. 提交边界

按 [UI_IMPLEMENTATION_PLAN.md](UI_IMPLEMENTATION_PLAN.md) 的"tokens only"边界，v0.9 token 重写拆四个 commit：

1. `tokens(android)`：4 个 sibling token class + ThemeVisuals 追加字段 + 测试。**不动任何 screen 文件**。
2. `tokens(web)`：抽 `shared/tokens.css` + 5 主题块 + alias shim；`web.css` 删原 `:root` 块改 `@import`。
3. `tokens(owner)`：`owner.css` 接入共享 token + `[data-owner]` 密度覆写 + 硬编码色全部替换 `var(--...)`。
4. `docs(v0.9)`：本文档。

每个 commit 落地后跑各端只读验证（Android `assembleGrayDebug` + `testGrayDebugUnitTest` + `lintGrayDebug`；Web/Owner `pytest -k web` 和 `pytest -k owner`）。

## 10. 已知约束 / 不在本轮做

- 不引入前端框架（`web.css` 顶部注释从 v0.4 起就这么写）
- 不在 `base.html` 落 `data-theme`，本轮纯 token
- 不批量改业务页面卡片 / Hero / 按钮 / 背景样式
- 不改 ViewModel / Repository / API 调用
- 身份契约 `identity_schema=v0.3` 不动
- Android `ThemeVisuals` 现有 17 字段名 / 顺序不动
- 图表 series N=8 锁死，超过类目数由消费页面建 "Other" 桶
- Owner 不消费 atmosphere token（`--atmo-*` 实际只在 Android 渲染）
