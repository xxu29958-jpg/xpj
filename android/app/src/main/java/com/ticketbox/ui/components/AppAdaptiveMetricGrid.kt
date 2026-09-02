package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing

internal enum class AppAdaptiveMetricGridMode {
    SingleColumn,
    TwoColumn,
}

/**
 * 紧凑指标（短标签 + 小号金额）的双列门槛：默认阈值面向大卡片，胶囊内容 300dp 已足够两列。
 * 实测约束（W2-C review-fix 真机图）：360dp 屏 @480dpi 内容区 x72..1008px → 真实 grid
 * maxWidth 312dp（两侧各 24dp 页边距），阈值必须低于 312 而非 360。
 */
internal val AppAdaptiveMetricGridCompactMinWidth = 300.dp

@Composable
fun AppAdaptiveMetricGrid(
    itemCount: Int,
    modifier: Modifier = Modifier,
    twoColumnMinWidth: Dp = AppAdaptiveBreakpoints.mediumWidthMin,
    item: @Composable (index: Int, modifier: Modifier) -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        when (resolveAppAdaptiveMetricGridMode(maxWidth, twoColumnMinWidth)) {
            AppAdaptiveMetricGridMode.SingleColumn -> AppAdaptiveMetricGridColumn(
                itemCount = itemCount,
                item = item,
            )
            AppAdaptiveMetricGridMode.TwoColumn -> AppAdaptiveMetricGridTwoColumn(
                itemCount = itemCount,
                item = item,
            )
        }
    }
}

@Composable
private fun AppAdaptiveMetricGridColumn(
    itemCount: Int,
    item: @Composable (index: Int, modifier: Modifier) -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        repeat(itemCount.coerceAtLeast(0)) { index ->
            item(index, Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun AppAdaptiveMetricGridTwoColumn(
    itemCount: Int,
    item: @Composable (index: Int, modifier: Modifier) -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        val safeCount = itemCount.coerceAtLeast(0)
        for (index in 0 until safeCount step 2) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                item(index, Modifier.weight(1f))
                if (index + 1 < safeCount) {
                    item(index + 1, Modifier.weight(1f))
                } else {
                    Spacer(modifier = Modifier.weight(1f))
                }
            }
        }
    }
}

internal fun resolveAppAdaptiveMetricGridMode(
    maxWidth: Dp,
    twoColumnMinWidth: Dp = AppAdaptiveBreakpoints.mediumWidthMin,
): AppAdaptiveMetricGridMode =
    if (maxWidth < twoColumnMinWidth) {
        AppAdaptiveMetricGridMode.SingleColumn
    } else {
        AppAdaptiveMetricGridMode.TwoColumn
    }
