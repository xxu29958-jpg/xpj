package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.BACKGROUND_TASK_CANCELLED
import com.ticketbox.domain.model.BACKGROUND_TASK_COMPLETED
import com.ticketbox.domain.model.BACKGROUND_TASK_FAILED
import com.ticketbox.domain.model.BACKGROUND_TASK_QUEUED
import com.ticketbox.domain.model.BACKGROUND_TASK_RUNNING
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.shouldGeneralizeTaskError
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.BackgroundTasksViewModel
import com.valentinilk.shimmer.shimmer

@Composable
fun BackgroundTasksScreen(
    viewModel: BackgroundTasksViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) {
        viewModel.refresh()
    }

    SettingsPageFrame(
        title = stringResource(R.string.background_tasks_page_title),
        subtitle = stringResource(R.string.background_tasks_page_subtitle),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = MessageTone.Neutral) },
    ) {
        SettingsSection(title = stringResource(R.string.background_tasks_section_recent_title), icon = Icons.Filled.Tune) {
            SettingsOpenPanel(
                verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                if (state.tasks.isEmpty() && state.loading) {
                    Column(modifier = Modifier.shimmer()) {
                        repeat(3) { ListItemSkeleton(horizontalPadding = 0.dp) }
                    }
                } else if (state.tasks.isEmpty()) {
                    Text(
                        text = stringResource(R.string.background_tasks_empty),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                state.tasks.forEach { task ->
                    TaskRow(
                        task = task,
                        busy = state.busyTaskId == task.publicId,
                        onCancel = { viewModel.cancel(task.publicId) },
                    )
                }
                OutlinedButton(
                    onClick = { viewModel.refresh() },
                    enabled = !state.loading && state.busyTaskId == null,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(if (state.loading) stringResource(R.string.background_tasks_refreshing) else stringResource(R.string.background_tasks_refresh)) }
            }
        }
    }
}

@Composable
private fun TaskRow(
    task: BackgroundTask,
    busy: Boolean,
    onCancel: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = stringResource(backgroundTaskTypeLabelRes(task.taskType)),
                style = MaterialTheme.typography.titleSmall,
            )
            Text(
                text = stringResource(backgroundTaskStatusLabelRes(task.status)),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.secondary,
            )
        }
        Text(
            text = stringResource(R.string.background_tasks_row_created, displayTime(task.createdAt)),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        task.completedAt?.let {
            Text(
                text = stringResource(R.string.background_tasks_row_finished, displayTime(it)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (task.progressTotal != null && task.progressTotal > 0) {
            LinearProgressIndicator(
                progress = {
                    (task.progressCurrent.toFloat() / task.progressTotal.toFloat())
                        .coerceIn(0f, 1f)
                },
                modifier = Modifier.fillMaxWidth(),
            )
        }
        task.progressMessage?.takeIf { it.isNotBlank() }?.let {
            Text(
                text = it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        task.errorMessage?.takeIf { it.isNotBlank() }?.let { rawError ->
            // Keep raw backend/engine errors out of ordinary user-facing copy.
            val genericError = stringResource(R.string.background_tasks_row_error_generic)
            Text(
                text = if (shouldGeneralizeTaskError(rawError)) genericError else rawError,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
        if (task.isCancellable) {
            OutlinedButton(
                onClick = onCancel,
                enabled = !busy,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (busy) stringResource(R.string.background_tasks_row_cancelling) else stringResource(R.string.background_tasks_row_request_cancel)) }
        }
    }
}

@StringRes
internal fun backgroundTaskStatusLabelRes(status: String): Int = when (status) {
    BACKGROUND_TASK_QUEUED -> R.string.background_tasks_status_queued
    BACKGROUND_TASK_RUNNING -> R.string.background_tasks_status_running
    BACKGROUND_TASK_COMPLETED -> R.string.background_tasks_status_completed
    BACKGROUND_TASK_FAILED -> R.string.background_tasks_status_failed
    BACKGROUND_TASK_CANCELLED -> R.string.background_tasks_status_cancelled
    else -> R.string.background_tasks_status_unknown
}

@StringRes
internal fun backgroundTaskTypeLabelRes(taskType: String): Int = when (taskType) {
    "csv_import" -> R.string.background_tasks_type_csv_import
    else -> R.string.background_tasks_type_unknown
}
