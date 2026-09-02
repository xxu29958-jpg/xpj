package com.ticketbox.ui.design

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.window.core.layout.WindowSizeClass.Companion.WIDTH_DP_EXPANDED_LOWER_BOUND
import androidx.window.core.layout.WindowSizeClass.Companion.WIDTH_DP_MEDIUM_LOWER_BOUND

enum class AppAdaptivePageMode {
    SingleColumn,
    WideContent,
    TwoPane,
}

enum class AppAdaptiveContentWidth {
    FullWidth,
    Secondary,
    Wide,
    TwoPane,
    Focus,
}

object AppAdaptiveBreakpoints {
    /** Android's official Compact → Medium width boundary. */
    val mediumWidthMin: Dp = WIDTH_DP_MEDIUM_LOWER_BOUND.dp

    /** Android's official Medium → Expanded width boundary. */
    val expandedWidthMin: Dp = WIDTH_DP_EXPANDED_LOWER_BOUND.dp

    val secondaryContentMaxWidth: Dp = 720.dp
    val wideContentMaxWidth: Dp = 840.dp
    val twoPaneContentMaxWidth: Dp = 1040.dp

    /**
     * 单一主任务焦点内容（空态引导、绑定/入门表单）在中宽以上窗口的列宽上限：
     * 内容居中、主操作不再横跨整窗。compact 单栏不适用（全宽）。
     * 当前真实消费者：收件空态卡、BindServerScreen。
     */
    val focusContentMaxWidth: Dp = 480.dp

    val pairedActionInlineMinWidth: Dp = 320.dp
    val contentActionInlineMinWidth: Dp = 360.dp
    val editActionInlineMinWidth: Dp = 380.dp
    val amountRowInlineMinWidth: Dp = 380.dp

    fun pageModeFor(maxWidth: Dp): AppAdaptivePageMode = when {
        maxWidth < mediumWidthMin -> AppAdaptivePageMode.SingleColumn
        maxWidth < expandedWidthMin -> AppAdaptivePageMode.WideContent
        else -> AppAdaptivePageMode.TwoPane
    }

    fun contentMaxWidthFor(policy: AppAdaptiveContentWidth, maxWidth: Dp): Dp? {
        val mode = pageModeFor(maxWidth)
        if (mode == AppAdaptivePageMode.SingleColumn) return null

        return when (policy) {
            AppAdaptiveContentWidth.FullWidth -> null
            AppAdaptiveContentWidth.Secondary -> secondaryContentMaxWidth
            AppAdaptiveContentWidth.Wide -> if (mode == AppAdaptivePageMode.WideContent) {
                wideContentMaxWidth
            } else {
                twoPaneContentMaxWidth
            }
            AppAdaptiveContentWidth.TwoPane -> if (mode == AppAdaptivePageMode.TwoPane) {
                twoPaneContentMaxWidth
            } else {
                null
            }
            AppAdaptiveContentWidth.Focus -> focusContentMaxWidth
        }
    }
}
