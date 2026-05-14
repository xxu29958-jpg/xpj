package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun PendingOverviewCard(summary: DataQualitySummary) {
    if (summary.pendingTotal == 0 &&
        summary.missingAmount == 0 &&
        summary.missingMerchant == 0 &&
        summary.missingCategory == 0 &&
        summary.suspectedDuplicates == 0 &&
        summary.readyToConfirm == 0
    ) {
        return
    }
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(9.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "待确认概况",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Black,
                )
                Text(
                    text = summary.oldestPendingAgeDays?.let { "最久 $it 天" } ?: "—",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            val visibleMetrics = pendingOverviewMetrics(summary)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                visibleMetrics.take(3).forEach { metric ->
                    MetricCell(Modifier.weight(1f), metric.label, metric.value)
                }
            }
            if (visibleMetrics.size > 3) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    visibleMetrics.drop(3).take(3).forEach { metric ->
                        MetricCell(Modifier.weight(1f), metric.label, metric.value)
                    }
                    repeat(3 - visibleMetrics.drop(3).take(3).size) {
                        Box(modifier = Modifier.weight(1f))
                    }
                }
            }
            Text(
                text = "去待确认页处理，整理后这里会清零。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun MetricCell(
    modifier: Modifier,
    label: String,
    value: Int,
) {
    val visuals = LocalThemeVisuals.current
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(visuals.chipUnselected.copy(alpha = 0.55f))
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                text = label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
            )
            Text(
                text = value.toString(),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Black,
                color = if (value > 0) {
                    MaterialTheme.colorScheme.onSurface
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
        }
    }
}

private data class PendingOverviewMetric(
    val label: String,
    val value: Int,
)

private fun pendingOverviewMetrics(summary: DataQualitySummary): List<PendingOverviewMetric> {
    val metrics = mutableListOf(
        PendingOverviewMetric("待确认", summary.pendingTotal),
        PendingOverviewMetric("可确认", summary.readyToConfirm),
    )
    if (summary.missingAmount > 0) metrics += PendingOverviewMetric("缺金额", summary.missingAmount)
    if (summary.missingMerchant > 0) metrics += PendingOverviewMetric("缺商家", summary.missingMerchant)
    if (summary.missingCategory > 0) metrics += PendingOverviewMetric("未分类", summary.missingCategory)
    if (summary.suspectedDuplicates > 0) metrics += PendingOverviewMetric("重复", summary.suspectedDuplicates)
    return metrics.take(6)
}
