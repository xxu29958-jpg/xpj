package com.ticketbox.ui.screens.pending

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

internal enum class PendingQueuePriority {
    Duplicate,
    Amount,
    Merchant,
    Ready,
    Review,
    Empty,
}

internal data class PendingQueueOverviewModel(
    val reviewCount: Int,
    val readyCount: Int,
    val needsAmount: Int,
    val needsMerchant: Int,
    val duplicate: Int,
    val priority: PendingQueuePriority,
)

internal fun pendingQueueOverviewModel(counts: PendingQueueCounts): PendingQueueOverviewModel {
    val all = counts.all.coerceAtLeast(0)
    val ready = counts.readyToConfirm.coerceIn(0, all)
    val needsAmount = counts.needsAmount.coerceAtLeast(0)
    val needsMerchant = counts.needsMerchant.coerceAtLeast(0)
    val duplicate = counts.duplicate.coerceAtLeast(0)
    return PendingQueueOverviewModel(
        reviewCount = all - ready,
        readyCount = ready,
        needsAmount = needsAmount,
        needsMerchant = needsMerchant,
        duplicate = duplicate,
        priority = pendingQueuePriority(all, ready, needsAmount, needsMerchant, duplicate),
    )
}

private fun pendingQueuePriority(
    all: Int,
    ready: Int,
    needsAmount: Int,
    needsMerchant: Int,
    duplicate: Int,
): PendingQueuePriority = when {
    all <= 0 -> PendingQueuePriority.Empty
    duplicate > 0 -> PendingQueuePriority.Duplicate
    needsAmount > 0 -> PendingQueuePriority.Amount
    needsMerchant > 0 -> PendingQueuePriority.Merchant
    ready > 0 -> PendingQueuePriority.Ready
    else -> PendingQueuePriority.Review
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun PendingQueueOverview(
    counts: PendingQueueCounts,
    readOnly: Boolean,
    bulkRunning: Boolean,
    onOpenBulkConfirm: () -> Unit,
) {
    val model = pendingQueueOverviewModel(counts)
    if (model.priority == PendingQueuePriority.Empty) return
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.tinyGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        PendingQueueOverviewHeader(
            model = model,
            readOnly = readOnly,
            bulkRunning = bulkRunning,
            onOpenBulkConfirm = onOpenBulkConfirm,
        )
        Text(
            text = pendingQueuePriorityText(model),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            if (model.shouldShowMetrics) {
                PendingQueueMetric(
                    label = stringResource(R.string.pending_queue_overview_ready_label),
                    value = model.readyCount,
                )
                PendingQueueMetric(
                    label = stringResource(R.string.pending_queue_overview_review_label),
                    value = model.reviewCount,
                )
            }
            if (model.hasReviewSignals) {
                PendingQueueIssue(model.needsAmount, R.string.pending_queue_overview_amount_issue)
                PendingQueueIssue(model.needsMerchant, R.string.pending_queue_overview_merchant_issue)
                PendingQueueIssue(model.duplicate, R.string.pending_queue_overview_duplicate_issue)
            }
        }
    }
}

@Composable
private fun PendingQueueOverviewHeader(
    model: PendingQueueOverviewModel,
    readOnly: Boolean,
    bulkRunning: Boolean,
    onOpenBulkConfirm: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(R.string.pending_queue_overview_title),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Spacer(modifier = Modifier.weight(1f))
        if (!readOnly && model.hasBatchConfirmAction) {
            TextButton(
                enabled = !bulkRunning,
                onClick = onOpenBulkConfirm,
                contentPadding = PaddingValues(horizontal = AppSpacing.miniGap),
            ) {
                Text(
                    text = if (bulkRunning) {
                        stringResource(R.string.pending_queue_overview_bulk_running)
                    } else {
                        stringResource(R.string.pending_queue_overview_bulk_confirm, model.readyCount)
                    },
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
            }
        }
    }
}

private val PendingQueueOverviewModel.hasReviewSignals: Boolean
    get() = needsAmount > 0 || needsMerchant > 0 || duplicate > 0

private val PendingQueueOverviewModel.hasBatchConfirmAction: Boolean
    get() = readyCount > 1

private val PendingQueueOverviewModel.shouldShowMetrics: Boolean
    get() = readyCount > 0 && reviewCount > 0

@Composable
private fun pendingQueuePriorityText(model: PendingQueueOverviewModel): String = when (model.priority) {
    PendingQueuePriority.Duplicate -> stringResource(R.string.pending_queue_overview_priority_duplicate)
    PendingQueuePriority.Amount -> stringResource(R.string.pending_queue_overview_priority_amount)
    PendingQueuePriority.Merchant -> stringResource(R.string.pending_queue_overview_priority_merchant)
    PendingQueuePriority.Ready -> stringResource(R.string.pending_queue_overview_priority_ready, model.readyCount)
    PendingQueuePriority.Review -> stringResource(R.string.pending_queue_overview_priority_review)
    PendingQueuePriority.Empty -> stringResource(R.string.pending_queue_overview_priority_empty)
}

@Composable
private fun PendingQueueMetric(label: String, value: Int) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontWeight = AppTextHierarchy.caption.weight,
        )
        Text(
            text = stringResource(R.string.pending_queue_overview_metric_count, value),
            style = MaterialTheme.typography.labelMedium,
            fontWeight = AppTextHierarchy.heading.weight,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun PendingQueueIssue(count: Int, @StringRes labelRes: Int) {
    if (count <= 0) return
    Text(
        text = stringResource(labelRes, count),
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.primary,
        fontWeight = AppTextHierarchy.heading.weight,
    )
}
