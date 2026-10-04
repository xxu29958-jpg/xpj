package com.ticketbox.ui.screens.stats

import androidx.annotation.StringRes
import androidx.annotation.DrawableRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import com.ticketbox.R
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals

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
        visibleMetrics.forEach { metric ->
            PendingOverviewLine(
                metric = metric,
                onClick = { onRemediate(metric.primaryRemediation) },
            )
            metric.secondaryRemediation?.let { remediation ->
                AppSecondaryButton(
                    text = stringResource(R.string.stats_data_quality_open_uncategorized_transactions),
                    modifier = Modifier.fillMaxWidth(),
                    leadingIcon = ImageVector.vectorResource(R.drawable.ic_lucide_receipt_text),
                    onClick = { onRemediate(remediation) },
                )
            }
        }
        if (summary.pendingTotal > 0) {
            Text(
                text = stringResource(R.string.dashboard_pending_count, summary.pendingTotal),
                style = MaterialTheme.typography.bodyMedium,
            )
            summary.oldestPendingAgeDays?.let { oldestDays ->
                Text(stringResource(R.string.stats_pending_overview_oldest, oldestDays),
                    color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            }
            Text(
                text = stringResource(R.string.stats_pending_overview_hint),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            AppSecondaryButton(
                text = stringResource(R.string.stats_data_quality_open_inbox),
                modifier = Modifier.fillMaxWidth(),
                leadingIcon = ImageVector.vectorResource(R.drawable.ic_lucide_inbox),
                onClick = { onRemediate(DataQualityRemediation.InboxAll) },
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
    ) {
        val visuals = LocalThemeVisuals.current
        SettingsEntryIcon(
            icon = ImageVector.vectorResource(metric.primaryRemediation.iconRes),
            modifier = Modifier.padding(end = AppSpacing.contentGap).align(Alignment.CenterVertically),
            background = when (metric.primaryRemediation) {
                DataQualityRemediation.InboxMissingFx -> visuals.surfaceApricot
                DataQualityRemediation.TransactionsConfirmedWithoutImage -> visuals.surfaceLilac
                else -> visuals.brandPrimaryBg
            },
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = stringResource(metric.labelRes),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.stats_data_quality_remediation_summary, metric.value,
                    stringResource(metric.primaryRemediation.destinationHintRes)),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Icon(
            imageVector = ImageVector.vectorResource(R.drawable.ic_lucide_chevron_right),
            contentDescription = stringResource(R.string.stats_data_quality_remediation_content_description),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.align(Alignment.CenterVertically),
        )
    }
}

internal enum class DataQualityRemediation(
    @param:StringRes val destinationHintRes: Int,
    @param:DrawableRes val iconRes: Int,
) {
    InboxAll(R.string.stats_data_quality_remediation_inbox_hint, R.drawable.ic_lucide_inbox),
    InboxReady(R.string.stats_data_quality_remediation_inbox_hint, R.drawable.ic_lucide_check),
    InboxMissingAmount(R.string.stats_data_quality_remediation_inbox_hint, R.drawable.ic_lucide_receipt_text),
    InboxMissingFx(R.string.stats_data_quality_remediation_inbox_hint, R.drawable.ic_lucide_globe),
    InboxMissingMerchant(R.string.stats_data_quality_remediation_inbox_hint, R.drawable.ic_lucide_store),
    InboxMissingCategory(R.string.stats_data_quality_remediation_inbox_hint, R.drawable.ic_lucide_tag),
    InboxDuplicate(R.string.stats_data_quality_remediation_inbox_hint, R.drawable.ic_lucide_copy),
    TransactionsMissingCategory(R.string.stats_data_quality_remediation_transactions_hint, R.drawable.ic_lucide_tag),
    TransactionsConfirmedWithoutImage(R.string.stats_data_quality_remediation_transactions_hint, R.drawable.ic_lucide_image),
}

internal data class PendingOverviewMetric(
    @param:StringRes val labelRes: Int,
    val value: Int,
    val primaryRemediation: DataQualityRemediation,
    val secondaryRemediation: DataQualityRemediation? = null,
)

internal fun pendingOverviewMetrics(summary: DataQualitySummary): List<PendingOverviewMetric> {
    val metrics = mutableListOf<PendingOverviewMetric>()
    // Inbox ReadyToConfirm routes uncategorized rows to quick-category before
    // confirm, so the ready line uses the categorized caliber — the count the
    // tap lands on. An N-1 backend doesn't send it; the legacy aggregate
    // counts rows the destination excludes, so per PROTOCOL_EVOLUTION the
    // actionable line is gated instead of advertising a mismatched route.
    val readyCount = summary.readyToConfirmCategorized
    if (readyCount != null && readyCount > 0) {
        metrics += PendingOverviewMetric(
            R.string.stats_pending_metric_ready,
            readyCount,
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
    if (summary.missingFx > 0) {
        metrics += PendingOverviewMetric(R.string.expense_fx_waiting, summary.missingFx, DataQualityRemediation.InboxMissingFx)
    }
    if (summary.missingMerchant > 0) {
        metrics += PendingOverviewMetric(
            R.string.stats_pending_metric_missing_merchant,
            summary.missingMerchant,
            DataQualityRemediation.InboxMissingMerchant,
        )
    }
    metrics += missingCategoryMetrics(summary)
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

// Backend missing_category mixes pending + confirmed rows; each status has
// its own remediation surface, so a current backend reports the composition
// and gets one line per part with the count that matches where the tap
// lands. An N-1 backend only sends the mixed total — show the pre-split
// single line with both remediation entries for it.
private fun missingCategoryMetrics(summary: DataQualitySummary): List<PendingOverviewMetric> {
    val pending = summary.missingCategoryPending
    val confirmed = summary.missingCategoryConfirmed
    if (pending == null || confirmed == null) {
        return if (summary.missingCategory > 0) {
            listOf(
                PendingOverviewMetric(
                    R.string.stats_pending_metric_missing_category,
                    summary.missingCategory,
                    DataQualityRemediation.InboxMissingCategory,
                    DataQualityRemediation.TransactionsMissingCategory,
                ),
            )
        } else {
            emptyList()
        }
    }
    return buildList {
        if (pending > 0) {
            add(
                PendingOverviewMetric(
                    R.string.stats_pending_metric_missing_category_pending,
                    pending,
                    DataQualityRemediation.InboxMissingCategory,
                ),
            )
        }
        if (confirmed > 0) {
            add(
                PendingOverviewMetric(
                    R.string.stats_pending_metric_missing_category_confirmed,
                    confirmed,
                    DataQualityRemediation.TransactionsMissingCategory,
                ),
            )
        }
    }
}
