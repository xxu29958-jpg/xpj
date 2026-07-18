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
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing

internal enum class AppAdaptiveMetricGridMode {
    SingleColumn,
    TwoColumn,
}

@Composable
fun AppAdaptiveMetricGrid(
    itemCount: Int,
    modifier: Modifier = Modifier,
    item: @Composable (index: Int, modifier: Modifier) -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        when (resolveAppAdaptiveMetricGridMode(maxWidth)) {
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

internal fun resolveAppAdaptiveMetricGridMode(maxWidth: Dp): AppAdaptiveMetricGridMode =
    if (maxWidth < AppAdaptiveBreakpoints.mediumWidthMin) {
        AppAdaptiveMetricGridMode.SingleColumn
    } else {
        AppAdaptiveMetricGridMode.TwoColumn
    }
