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
}

object AppAdaptiveBreakpoints {
    /** Android's official Compact → Medium width boundary. */
    val mediumWidthMin: Dp = WIDTH_DP_MEDIUM_LOWER_BOUND.dp

    /** Android's official Medium → Expanded width boundary. */
    val expandedWidthMin: Dp = WIDTH_DP_EXPANDED_LOWER_BOUND.dp

    val secondaryContentMaxWidth: Dp = 720.dp
    val wideContentMaxWidth: Dp = 840.dp
    val twoPaneContentMaxWidth: Dp = 1040.dp

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
        return when (policy) {
            AppAdaptiveContentWidth.FullWidth -> null
            AppAdaptiveContentWidth.Secondary -> when (mode) {
                AppAdaptivePageMode.SingleColumn -> null
                AppAdaptivePageMode.WideContent,
                AppAdaptivePageMode.TwoPane -> secondaryContentMaxWidth
            }
            AppAdaptiveContentWidth.Wide -> when (mode) {
                AppAdaptivePageMode.SingleColumn -> null
                AppAdaptivePageMode.WideContent -> wideContentMaxWidth
                AppAdaptivePageMode.TwoPane -> twoPaneContentMaxWidth
            }
            AppAdaptiveContentWidth.TwoPane -> when (mode) {
                AppAdaptivePageMode.SingleColumn,
                AppAdaptivePageMode.WideContent -> null
                AppAdaptivePageMode.TwoPane -> twoPaneContentMaxWidth
            }
        }
    }
}
