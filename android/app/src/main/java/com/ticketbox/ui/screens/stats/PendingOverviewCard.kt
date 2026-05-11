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
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
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
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MetricCell(Modifier.weight(1f), "待确认", summary.pendingTotal)
                MetricCell(Modifier.weight(1f), "可直接确认", summary.readyToConfirm)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MetricCell(Modifier.weight(1f), "缺金额", summary.missingAmount)
                MetricCell(Modifier.weight(1f), "缺商家", summary.missingMerchant)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MetricCell(Modifier.weight(1f), "未分类", summary.missingCategory)
                MetricCell(Modifier.weight(1f), "疑似重复", summary.suspectedDuplicates)
            }
            Text(
                text = "去“待确认”页处理这些账单，整理后这里会清零。",
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
