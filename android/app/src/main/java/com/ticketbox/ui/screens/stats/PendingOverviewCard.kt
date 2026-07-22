package com.ticketbox.ui.screens.stats

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material3.Icon
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
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun PendingOverviewCard(
    summary: DataQualitySummary,
    onRemediate: (DataQualityRemediation) -> Unit,
) {
    val visibleMetrics = pendingOverviewMetrics(summary)
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        PendingOverviewHeader(summary)
        visibleMetrics.forEach { metric ->
            PendingOverviewLine(
                metric = metric,
                onClick = { onRemediate(metric.primaryRemediation) },
            )
        }
        if (summary.pendingTotal > 0) {
            Text(
                text = stringResource(R.string.stats_pending_overview_hint),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            AppSecondaryButton(
                text = stringResource(R.string.stats_data_quality_open_inbox),
                modifier = Modifier.fillMaxWidth(),
                leadingIcon = Icons.Default.Inbox,
                onClick = { onRemediate(DataQualityRemediation.InboxAll) },
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun PendingOverviewHeader(summary: DataQualitySummary) {
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
        Column(horizontalAlignment = Alignment.End) {
            Text(
                text = stringResource(R.string.stats_pending_metric_pending_total),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
            )
            Text(
                text = summary.pendingTotal.toString(),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleLarge.tabularNum(),
                fontWeight = AppTextHierarchy.heading.weight,
            )
        }
    }
}

@Composable
private fun PendingOverviewLine(
    metric: PendingOverviewMetric,
    onClick: () -> Unit,
) {
    AppListRow(
        onClick = onClick,
        showDivider = false,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = stringResource(metric.labelRes),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = stringResource(metric.primaryRemediation.destinationHintRes),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
            )
        }
        Text(
            text = metric.value.toString(),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall.tabularNum(),
            fontWeight = AppTextHierarchy.body.weight,
        )
        Icon(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = stringResource(R.string.stats_data_quality_remediation_content_description),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.align(Alignment.CenterVertically),
        )
    }
}

internal enum class DataQualityRemediation(
    @param:StringRes val destinationHintRes: Int,
) {
    InboxAll(R.string.stats_data_quality_remediation_inbox_hint),
    InboxReady(R.string.stats_data_quality_remediation_inbox_hint),
    InboxMissingAmount(R.string.stats_data_quality_remediation_inbox_hint),
    InboxMissingMerchant(R.string.stats_data_quality_remediation_inbox_hint),
    InboxMissingCategory(R.string.stats_data_quality_remediation_inbox_hint),
    InboxDuplicate(R.string.stats_data_quality_remediation_inbox_hint),
    TransactionsMissingCategory(R.string.stats_data_quality_remediation_transactions_hint),
    TransactionsConfirmedWithoutImage(R.string.stats_data_quality_remediation_transactions_hint),
}

internal data class PendingOverviewMetric(
    @param:StringRes val labelRes: Int,
    val value: Int,
    val primaryRemediation: DataQualityRemediation,
)

internal fun pendingOverviewMetrics(summary: DataQualitySummary): List<PendingOverviewMetric> {
    val metrics = mutableListOf<PendingOverviewMetric>()
    // Inbox ReadyToConfirm routes uncategorized rows to quick-category before
    // confirm, so the ready line uses the categorized caliber — the mixed
    // backend ready_to_confirm would land on a shorter list than advertised.
    if (summary.readyToConfirmCategorized > 0) {
        metrics += PendingOverviewMetric(
            R.string.stats_pending_metric_ready,
            summary.readyToConfirmCategorized,
            DataQualityRemediation.InboxReady,
        )
    }
    if (summary.missingAmount > 0) {
        metrics += PendingOverviewMetric(
            R.string.stats_pending_metric_missing_amount,
            summary.missingAmount,
            DataQualityRemediation.InboxMissingAmount,
        )
    }
    if (summary.missingMerchant > 0) {
        metrics += PendingOverviewMetric(
            R.string.stats_pending_metric_missing_merchant,
            summary.missingMerchant,
            DataQualityRemediation.InboxMissingMerchant,
        )
    }
    // Backend missing_category mixes pending + confirmed rows; each status has
    // its own remediation surface, so show one line per part with the count
    // that matches where the tap lands.
    if (summary.missingCategoryPending > 0) {
        metrics += PendingOverviewMetric(
            R.string.stats_pending_metric_missing_category_pending,
            summary.missingCategoryPending,
            DataQualityRemediation.InboxMissingCategory,
        )
    }
    if (summary.missingCategoryConfirmed > 0) {
        metrics += PendingOverviewMetric(
            R.string.stats_pending_metric_missing_category_confirmed,
            summary.missingCategoryConfirmed,
            DataQualityRemediation.TransactionsMissingCategory,
        )
    }
    if (summary.suspectedDuplicates > 0) {
        metrics += PendingOverviewMetric(
            R.string.stats_pending_metric_duplicates,
            summary.suspectedDuplicates,
            DataQualityRemediation.InboxDuplicate,
        )
    }
    if (summary.confirmedWithoutImage > 0) {
        metrics += PendingOverviewMetric(
            R.string.stats_pending_metric_confirmed_without_image,
            summary.confirmedWithoutImage,
            DataQualityRemediation.TransactionsConfirmedWithoutImage,
        )
    }
    return metrics
}
