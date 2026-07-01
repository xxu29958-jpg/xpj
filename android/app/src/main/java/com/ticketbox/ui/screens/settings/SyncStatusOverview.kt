package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

internal data class SyncStatusOverview(
    val queuedCount: Int,
    val conflictCount: Int,
    val failedCount: Int,
) {
    val needsActionCount: Int = conflictCount + failedCount
    val isSettled: Boolean = queuedCount == 0 && needsActionCount == 0
}

internal fun syncStatusOverview(status: OutboxStatus): SyncStatusOverview =
    SyncStatusOverview(
        queuedCount = status.queueDepth.coerceAtLeast(0),
        conflictCount = status.conflicts.size,
        failedCount = status.failed.size,
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
            SyncStatusOverviewStrip(overview)
            Text(
                text = overviewCaption(overview),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun SyncStatusOverviewStrip(overview: SyncStatusOverview) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        SyncStatusOverviewMetric(
            label = stringResource(R.string.sync_status_overview_queued_label),
            value = overview.queuedCount,
            caption = stringResource(R.string.sync_status_overview_queued_caption),
            modifier = Modifier.weight(1f),
        )
        SyncStatusOverviewMetric(
            label = stringResource(R.string.sync_status_overview_conflicts_label),
            value = overview.conflictCount,
            caption = stringResource(R.string.sync_status_overview_conflicts_caption),
            modifier = Modifier.weight(1f),
        )
        SyncStatusOverviewMetric(
            label = stringResource(R.string.sync_status_overview_failed_label),
            value = overview.failedCount,
            caption = stringResource(R.string.sync_status_overview_failed_caption),
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun SyncStatusOverviewMetric(
    label: String,
    value: Int,
    caption: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
        )
        Text(
            text = value.toString(),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleMedium.tabularNum(),
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = caption,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 2,
        )
    }
}

@Composable
private fun overviewCaption(overview: SyncStatusOverview): String = when {
    overview.needsActionCount > 0 -> stringResource(
        R.string.sync_status_overview_caption_needs_action,
        overview.needsActionCount,
    )
    overview.queuedCount > 0 -> stringResource(R.string.sync_status_overview_caption_queued)
    else -> stringResource(R.string.sync_status_overview_caption_settled)
}
