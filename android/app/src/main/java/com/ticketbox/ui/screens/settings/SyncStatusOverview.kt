package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.ui.design.AppSpacing

internal data class SyncStatusOverview(
    val queuedCount: Int,
    val conflictCount: Int,
    val failedCount: Int,
    val quarantinedCount: Int,
) {
    val needsActionCount: Int = conflictCount + failedCount + quarantinedCount
    val isSettled: Boolean = queuedCount == 0 && needsActionCount == 0
}

internal fun syncStatusOverview(status: OutboxStatus): SyncStatusOverview =
    SyncStatusOverview(
        queuedCount = status.queueDepth.coerceAtLeast(0),
        conflictCount = status.conflicts.size,
        failedCount = status.failed.size,
        quarantinedCount = status.quarantinedCount.coerceAtLeast(0),
    )

@Composable
internal fun SyncStatusOverviewSection(status: OutboxStatus) {
    val overview = syncStatusOverview(status)
    SettingsSection(
        title = stringResource(R.string.sync_status_overview_title),
        icon = Icons.Filled.Sync,
    ) {
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            SettingsMetricGrid(
                metrics = listOf(
                    SettingsMetricData(
                        label = stringResource(R.string.sync_status_overview_queued_label),
                        value = overview.queuedCount.toString(),
                        caption = stringResource(R.string.sync_status_overview_queued_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.sync_status_overview_conflicts_label),
                        value = overview.conflictCount.toString(),
                        caption = stringResource(R.string.sync_status_overview_conflicts_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.sync_status_overview_failed_label),
                        value = overview.failedCount.toString(),
                        caption = stringResource(R.string.sync_status_overview_failed_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.sync_status_overview_quarantined_label),
                        value = overview.quarantinedCount.toString(),
                        caption = stringResource(R.string.sync_status_overview_quarantined_caption),
                    ),
                ),
            )
            Text(
                text = overviewCaption(overview),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun overviewCaption(overview: SyncStatusOverview): String = when {
    overview.quarantinedCount > 0 -> stringResource(
        R.string.sync_status_overview_caption_quarantined,
        overview.quarantinedCount,
    )
    overview.needsActionCount > 0 -> stringResource(
        R.string.sync_status_overview_caption_needs_action,
        overview.needsActionCount,
    )
    overview.queuedCount > 0 -> stringResource(R.string.sync_status_overview_caption_queued)
    else -> stringResource(R.string.sync_status_overview_caption_settled)
}
