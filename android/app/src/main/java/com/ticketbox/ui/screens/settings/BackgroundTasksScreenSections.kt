package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.valentinilk.shimmer.shimmer

@Composable
internal fun BackgroundTasksOverview(summary: BackgroundTasksSummaryModel) {
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            BackgroundTaskMetric(
                label = stringResource(R.string.background_tasks_summary_total_label),
                value = summary.totalCount,
                modifier = Modifier.weight(1f),
            )
            BackgroundTaskMetric(
                label = stringResource(R.string.background_tasks_summary_active_label),
                value = summary.activeCount,
                modifier = Modifier.weight(1f),
            )
            BackgroundTaskMetric(
                label = stringResource(R.string.background_tasks_summary_failed_label),
                value = summary.failedCount,
                modifier = Modifier.weight(1f),
            )
        }
        Text(
            text = backgroundTasksSummaryCaption(summary),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
internal fun BackgroundTasksRows(
    tasks: List<BackgroundTask>,
    loading: Boolean,
    busyTaskId: String?,
    onCancel: (String) -> Unit,
) {
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
    SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(0.dp)) {
        when {
            tasks.isEmpty() && loading -> BackgroundTasksSkeleton()
            tasks.isEmpty() -> SettingsInlineEmpty(
                title = stringResource(R.string.background_tasks_empty_title),
                body = stringResource(R.string.background_tasks_empty),
            )
            else -> tasks.forEachIndexed { index, task ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
                }
                BackgroundTaskRow(
                    task = task,
                    busy = busyTaskId == task.publicId,
                    onCancel = { onCancel(task.publicId) },
                )
            }
        }
    }
}

@Composable
internal fun BackgroundTasksRefreshAction(
    loading: Boolean,
    busy: Boolean,
    onRefresh: () -> Unit,
) {
    val enabled = !loading && !busy
    val color = if (enabled) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(AppRadius.small))
            .clickable(enabled = enabled, role = Role.Button, onClick = onRefresh)
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Filled.Refresh,
            contentDescription = null,
            tint = color,
            modifier = Modifier.size(AppSpacing.cardPadding),
        )
        Text(
            text = if (loading) {
                stringResource(R.string.background_tasks_refreshing)
            } else {
                stringResource(R.string.background_tasks_refresh)
            },
            color = color,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
    }
}

@Composable
private fun BackgroundTaskMetric(
    label: String,
    value: Int,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = stringResource(R.string.background_tasks_summary_count, value),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
        )
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
        )
    }
}

@Composable
private fun backgroundTasksSummaryCaption(summary: BackgroundTasksSummaryModel): String =
    when (summary.state) {
        BackgroundTasksSummaryState.Loading -> stringResource(R.string.background_tasks_summary_loading)
        BackgroundTasksSummaryState.Empty -> stringResource(R.string.background_tasks_summary_empty)
        BackgroundTasksSummaryState.Active -> stringResource(
            R.string.background_tasks_summary_active,
            summary.activeCount,
            summary.cancellableCount,
        )
        BackgroundTasksSummaryState.Failed -> stringResource(
            R.string.background_tasks_summary_failed,
            summary.failedCount,
        )
        BackgroundTasksSummaryState.Settled -> stringResource(R.string.background_tasks_summary_settled)
    }

@Composable
private fun BackgroundTasksSkeleton() {
    Column(modifier = Modifier.shimmer()) {
        repeat(3) { ListItemSkeleton(horizontalPadding = 0.dp) }
    }
}
