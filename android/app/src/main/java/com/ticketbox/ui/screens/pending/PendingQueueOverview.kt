package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
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

/**
 * Counts live on the filter chips below. The overview only adds what no chip can say: the
 * duplicate-entry risk, why a local snapshot cannot be bulk-confirmed, and the bulk action.
 */
internal enum class PendingQueueNotice {
    Duplicate,
    LocalCache,
}

internal enum class PendingQueueEvidence {
    Backend,
    LocalCache,
}

internal data class PendingQueueOverviewModel(
    val visible: Boolean,
    val readyCount: Int,
    val needsInformation: Int,
    val duplicate: Int,
    val notice: PendingQueueNotice?,
    val evidence: PendingQueueEvidence,
    val canBulkConfirm: Boolean,
)

internal fun pendingQueueOverviewModel(
    counts: PendingQueueCounts,
    evidence: PendingQueueEvidence = PendingQueueEvidence.Backend,
): PendingQueueOverviewModel {
    val all = counts.all.coerceAtLeast(0)
    val ready = counts.readyToConfirm.coerceIn(0, all)
    val duplicate = counts.duplicate.coerceAtLeast(0)
    return PendingQueueOverviewModel(
        visible = all > 0,
        readyCount = ready,
        needsInformation = counts.needsInformation.coerceAtLeast(0),
        duplicate = duplicate,
        notice = when {
            all <= 0 -> null
            evidence == PendingQueueEvidence.LocalCache -> PendingQueueNotice.LocalCache
            duplicate > 0 -> PendingQueueNotice.Duplicate
            else -> null
        },
        evidence = evidence,
        canBulkConfirm = evidence == PendingQueueEvidence.Backend && ready > 1,
    )
}

@Composable
internal fun PendingQueueOverview(
    counts: PendingQueueCounts,
    evidence: PendingQueueEvidence,
    readOnly: Boolean,
    bulkRunning: Boolean,
    onOpenBulkConfirm: () -> Unit,
) {
    val model = pendingQueueOverviewModel(counts, evidence)
    val showBulk = !readOnly && model.canBulkConfirm
    if (!model.visible || (model.notice == null && !showBulk)) return
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.tinyGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = model.notice?.let { pendingQueueNoticeText(it) }.orEmpty(),
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        if (showBulk) {
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

@Composable
private fun pendingQueueNoticeText(notice: PendingQueueNotice): String = when (notice) {
    PendingQueueNotice.Duplicate -> stringResource(R.string.pending_queue_overview_priority_duplicate)
    PendingQueueNotice.LocalCache -> stringResource(R.string.pending_queue_overview_priority_cache)
}
