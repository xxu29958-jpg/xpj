package com.ticketbox.ui.design

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

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
    val singleColumnMaxWidth: Dp = 599.dp
    val twoPaneMinWidth: Dp = 840.dp
    val secondaryContentMaxWidth: Dp = 720.dp
    val wideContentMaxWidth: Dp = 840.dp
    val twoPaneContentMaxWidth: Dp = 1040.dp

    val pairedActionInlineMinWidth: Dp = 320.dp
    val contentActionInlineMinWidth: Dp = 360.dp
    val editActionInlineMinWidth: Dp = 380.dp

    fun pageModeFor(maxWidth: Dp): AppAdaptivePageMode = when {
        maxWidth <= singleColumnMaxWidth -> AppAdaptivePageMode.SingleColumn
        maxWidth < twoPaneMinWidth -> AppAdaptivePageMode.WideContent
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
