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
2. `tokens only`：新增/迁移 design tokens，不改页面。
3. `components only`：新增 reusable components、preview/sample 和兼容 wrappers，不批量改业务屏幕。
4. `theme/background only`：ThemeVisuals、BackgroundVisuals、AppThemeBackground。
5. `PendingScreen only`：Pending 标杆页。
6. `LedgerScreen only`：账本视觉接入，保持扫读。
7. `StatsScreen only`：统计视觉和空状态。
8. `Settings / Appearance only`：设置和外观页统一。
9. `ExpenseEdit only`：编辑确认页视觉接入。
10. `UX states only`：loading / success / error / empty / offline / duplicate / OCR / CSV 状态。

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
