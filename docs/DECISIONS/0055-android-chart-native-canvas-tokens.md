# 0055 Android 图表回收到原生 Canvas 与设计 token

日期：2026-06-30

状态：accepted

Supersedes: [0025 v0.9 Android 图表库 Vico](0025-v0.9-android-chart-library-vico.md)

## 背景

ADR-0025 曾决定在 Android 展示层引入 Vico 3.1.0，用于 v0.9 报表趋势、排行和后续更复杂图表。实际 IA/UIUX 校准中，洞察页当前最需要解决的不是通用图表能力，而是趋势图语义不清、柱形/折线混用、深色模式下读数弱，以及页面过度卡片化。

本轮验证发现，Vico 接入会把轴、图例和组合图能力带进较小的手机屏幕，但当前数据主要是月内支出和最近 7 天支出。对这些轻量趋势，通用图表库反而更容易让界面显得僵硬，并且增加依赖面。用户也明确要求柱形图和折线图不要混在一起，可以删除不合适的依赖。

## 决策

Android 当前回收到原生 Compose Canvas 图表，并通过 `ui/design` 下的 chart/stats token 管理尺寸、颜色、透明度、圆角和密度。

约束如下：

- 洞察页趋势图不再混合柱形图和折线图。同一图表只表达一个主要问题。
- 月内支出、最近 7 天和报表趋势统一使用 tokenized `StatsSpendBarChart` 这类展示层组件。
- 后端仍是统计口径的唯一权威；Android 可以缓存和离线降级，但不得把缓存当作权威来源。
- 图表组件只消费 domain model，不改变 `/api/stats/*` 或 `/api/reports/*` 契约。
- 用户可见中文仍走 Android string resource。
- 如果未来确实需要缩放、复杂 tooltip、多系列交互、导出预览或更复杂的坐标轴能力，必须重新走 ADR-0023 的依赖审计流程。

## 影响

- 删除 Android Vico 运行时依赖：`com.patrykandpatrick.vico:compose-m3` 不再出现在 version catalog 和 app 依赖中。
- ADR-0025 保留为历史记录，但不再描述当前 Android 运行时状态。
- `/web` ECharts 决策 ADR-0026 不受影响。
- 当前洞察页趋势图以可读性和移动端节奏为先，保留原生 Canvas 回退能力。

## 验证

本决策对应代码改动必须至少运行：

```powershell
cd android
.\gradlew.bat :app:compileGrayDebugKotlin :app:detektGrayDebug
```

若触及更多 Android UI 或 ViewModel，再按 Android 规则追加 `detektGrayDebugUnitTest`、`testGrayDebugUnitTest`、`lintGrayDebug` 和真机/模拟器截图验证。
