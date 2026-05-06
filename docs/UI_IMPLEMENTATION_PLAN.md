# UI Implementation Plan

本轮目标是把设计包工程化为长期可维护的视觉系统，而不是继续局部修 padding。

## Non-goals

本轮不做：

- 新业务功能
- 新后端接口
- 新数据库字段，除非 Appearance / Background 已在前置任务明确需要
- 新 OCR 能力
- 新同步机制
- 新统计算法
- 新复杂动画库
- 新外部 UI 框架

本轮只做：

- 设计目标文档化
- 设计系统工程化
- 组件统一
- 页面视觉还原
- UX 状态反馈
- 截图验收

## Commit Boundaries

按以下顺序提交，不能混阶段：

1. `docs only`：设计参考、目标文档、实施计划、缩略图。
2. `page scaffold only`：统一页面骨架、安全区、滚动 padding 和底部避让，不做视觉还原。
3. `tokens only`：新增/迁移 design tokens，不改页面。
4. `components only`：新增 reusable components、preview/sample 和兼容 wrappers，不批量改业务屏幕。
5. `theme/background only`：ThemeVisuals、BackgroundVisuals、AppThemeBackground。
6. `PendingScreen only`：Pending 标杆页。
7. `LedgerScreen only`：账本视觉接入，保持扫读。
8. `StatsScreen only`：统计视觉和空状态。
9. `Settings / Appearance only`：设置和外观页统一。
10. `ExpenseEdit only`：编辑确认页视觉接入。
11. `UX states only`：loading / success / error / empty / offline / duplicate / OCR / CSV 状态。

## Definition of Done Per Commit

每个 commit 必须满足：

1. 能编译。
2. 不破坏现有业务流程。
3. 不引入大范围无关改动。
4. 不把多个阶段混在一起。
5. 有必要的说明或截图。
6. 如果是页面改造，必须保留原 ViewModel / Repository / API 调用逻辑。
7. 如果是视觉组件，必须有至少一个 preview、sample 或兼容 wrapper 使用它。

## Component Phase Restriction

组件阶段只新增组件、preview/sample 或兼容 wrapper。
不批量改业务页面。
只有进入 Pending benchmark 阶段后，才开始替换业务页面 UI。

## Page Scaffold Gate

`page scaffold only` 是设计包工程化的强制前置阶段。它先修全局页面骨架，不碰视觉还原、不改业务逻辑。

必须整理并真实接入：

- `AppPageScaffold`
- `AppPageHeader`
- `AppScrollableContent`
- `BottomBarAwarePadding`
- `PageRole`
- `PageDensity`

真实页面至少接入：

- Pending
- Ledger
- Stats
- Settings
- Edit

页面密度固定：

- `Pending = comfortable`
- `Stats = comfortable`
- `Settings = comfortable`
- `Ledger = compact`
- `Edit = compact`

默认 spacing 固定：

- `horizontalPadding = 24.dp`
- `compact.topContentPadding = 16.dp`
- `comfortable.topContentPadding = 24.dp`
- `compact.headerToContentGap = 16.dp`
- `comfortable.headerToContentGap = 22.dp`
- `compact.sectionGap = 18.dp`
- `comfortable.sectionGap = 24.dp`
- `cardGap = 16.dp`
- `bottomContentExtraPadding = 24.dp`

底部避让公式：

```text
scrollContentBottomPadding = bottomBarHeight + navigationBarsPadding + bottomContentExtraPadding
```

如果底栏高度暂时不能实测，必须使用命名常量 `AppPageDefaults.BottomBarHeight = 72.dp`，并在代码注释中标明后续可替换为实测布局值。禁止各页面写随机 `120.dp / 160.dp / 220.dp`。

Page scaffold 阶段只允许：

- 调整布局骨架。
- 统一安全区。
- 统一滚动内容 padding。
- 删除或替换大 `Spacer`。
- 替换重复的 per-screen top/bottom padding。

Page scaffold 阶段禁止：

- 重做卡片样式。
- 重做按钮样式。
- 重做背景样式。
- 重做 Hero 样式。
- 改主题视觉。
- 改 ViewModel / Repository / API 调用。
- 改上传、pending、confirmed、OCR、重复检测、Room、CSV、服务器绑定、分类规则数据流。

验收必须确认：

- 标题不裁切。
- 顶部不过空。
- 页面内容不整体下沉。
- 底部内容不被导航遮挡。
- 最后一项能完整滚到导航栏上方。
- 底部导航不跟随内容上移。
- Ledger / Edit 可读性不下降。

Page scaffold 通过后，才继续 `components only`、`theme/background only` 和 `PendingScreen only`。

## Pending Benchmark Gate

PendingScreen 是标杆页。在 PendingScreen 没有通过人工 review 前，不允许开始批量改 Ledger / Stats / Settings / Edit。

PendingScreen 通过标准：

1. 背景氛围接近设计包。
2. Hero 卡片有渐变、光感、阴影和层级。
3. 上传截图是清楚的主 CTA。
4. 空状态精致，不像默认 Material。
5. 底部导航统一。
6. loading / offline / empty 不遮挡标题。
7. 业务文案完整。
8. 真机截图人工通过。

## Ledger / Edit Readability Gate

Ledger 和 Edit 不追求最高沉浸。它们的优先级是：

1. 金额清楚。
2. 商家清楚。
3. 时间清楚。
4. 表单字段清楚。
5. 主操作按钮清楚。

如果视觉还原影响可读性，以可读性为准。

## Screenshot Acceptance

验收截图统一命名：

- `pending_empty.png`
- `pending_with_items.png`
- `pending_offline.png`
- `ledger_items.png`
- `ledger_search_empty.png`
- `stats_empty.png`
- `stats_with_data.png`
- `settings_root.png`
- `appearance.png`
- `background_gallery.png`
- `background_preview.png`
- `expense_edit.png`

截图放 `artifacts`，不提交大图。必要时只提交低分辨率验收缩略图。

每张截图对照 `docs/design_reference` 检查：

- 是否接近设计方向稿
- 是否有明显安全区问题
- 是否有文字裁切
- 是否有按钮贴边
- 是否有底部遮挡
- 是否金额不清楚
- 是否背景抢内容
- 是否还像普通 Material 默认 UI

## Post-Acceptance Polish Loop

视觉验收后允许继续小幅打磨，但必须按“发现一个真实问题、修一个可验证问题”的方式推进。

允许修：

- 顶部安全区、标题裁切、标题过低。
- 底部导航遮挡内容。
- 列表最后一项无法完整滚出。
- 账单卡片过高导致首屏信息不足。
- 表单页字段可读性不足。
- 空状态、离线状态、loading 状态遮挡主标题。
- 二级设置页返回按钮和页面标题间距异常。

禁止借 polish 名义继续做：

- 新业务功能。
- 新后端接口。
- 新数据库字段。
- 新 OCR 能力。
- 新同步策略。
- 大范围重写页面。
- 重做主题体系。
- 牺牲 Ledger / Edit 可读性的沉浸效果。

每轮 polish 必须：

1. 先用真机截图或 UI tree 确认问题。
2. 只改对应页面或通用骨架的最小范围。
3. 保留原 ViewModel / Repository / API 调用逻辑。
4. 刷新对应 `artifacts/*.png` 验收截图。
5. 更新 `docs/UI_SCREENSHOT_ACCEPTANCE.md` 或灰度状态文档。
6. 跑当前 gray 变体的测试、构建、lint。
7. 单独提交，不和新功能混在一起。

## Gradle Variant Fallback

使用项目实际 Gradle variant：

- 如果 gray flavor 存在，运行：
  - `.\gradlew.bat --no-daemon :app:assembleGrayDebug`
  - `.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest`
  - `.\gradlew.bat --no-daemon :app:lintGrayDebug`
- 如果 gray flavor 不存在，fallback 到：
  - `.\gradlew.bat --no-daemon :app:assembleDebug`
  - `.\gradlew.bat --no-daemon :app:testDebugUnitTest`
  - `.\gradlew.bat --no-daemon :app:lintDebug`

## Rollback Rule

如果某阶段导致大量页面异常，不要继续叠修。
先回退该阶段，重新拆小。

## Asset Strategy

- 不提交大 zip。
- 允许提交低分辨率 reference thumbnails。
- 不引入高风险 UI dependencies。
- 优先使用 Compose drawing、vector drawables 和 gradient brushes。
- Built-in backgrounds 第一版可用 gradient placeholders。
- ReceiptIllustration 可用 Compose/vector illustration。
