package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun PendingOverviewCard(summary: DataQualitySummary) {
    if (summary.pendingTotal <= 0) {
        return
    }

    val visibleMetrics = pendingOverviewMetrics(summary)
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
            verticalAlignment = Alignment.Bottom,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = stringResource(R.string.stats_pending_overview_title),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                summary.oldestPendingAgeDays?.let { oldestDays ->
                    Text(
                        text = stringResource(R.string.stats_pending_overview_oldest, oldestDays),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }
            Text(
                text = summary.pendingTotal.toString(),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleLarge.tabularNum(),
                fontWeight = AppTextHierarchy.heading.weight,
            )
        }
        visibleMetrics.forEach { metric ->
            PendingOverviewLine(metric = metric)
        }
        if (summary.pendingTotal > 0) {
            Text(
                text = stringResource(R.string.stats_pending_overview_hint),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun PendingOverviewLine(metric: PendingOverviewMetric) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = metric.label,
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = metric.value.toString(),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall.tabularNum(),
            fontWeight = AppTextHierarchy.body.weight,
        )
    }
}

private data class PendingOverviewMetric(
    val label: String,
    val value: Int,
)

@Composable
private fun pendingOverviewMetrics(summary: DataQualitySummary): List<PendingOverviewMetric> {
    val metrics = mutableListOf<PendingOverviewMetric>()
    if (summary.readyToConfirm > 0) {
        metrics += PendingOverviewMetric(stringResource(R.string.stats_pending_metric_ready), summary.readyToConfirm)
    }
    if (summary.missingAmount > 0) {
        metrics += PendingOverviewMetric(stringResource(R.string.stats_pending_metric_missing_amount), summary.missingAmount)
    }
    if (summary.missingMerchant > 0) {
        metrics += PendingOverviewMetric(stringResource(R.string.stats_pending_metric_missing_merchant), summary.missingMerchant)
    }
    if (summary.missingCategory > 0) {
        metrics += PendingOverviewMetric(stringResource(R.string.stats_pending_metric_missing_category), summary.missingCategory)
    }
    if (summary.suspectedDuplicates > 0) {
        metrics += PendingOverviewMetric(stringResource(R.string.stats_pending_metric_duplicates), summary.suspectedDuplicates)
    }
    return metrics
}
