package com.ticketbox.ui.screens.settings

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
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.backgroundTaskStatusLabel
import com.ticketbox.domain.model.backgroundTaskTypeLabel
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.BackgroundTasksViewModel
import com.valentinilk.shimmer.shimmer

/**
 * ADR-0030 PR-2b — Android task list.
 *
 * Mirrors `/web/tasks` UI: same data shape, same status labels, same
 * cancel-on-running semantics. No polling; user pulls to refresh.
 */
@Composable
fun BackgroundTasksScreen(
    viewModel: BackgroundTasksViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsState()

    LaunchedEffect(Unit) {
        viewModel.refresh()
    }

    SettingsPageFrame(
        title = stringResource(R.string.background_tasks_page_title),
        subtitle = stringResource(R.string.background_tasks_page_subtitle),
        onBack = onBack,
    ) {
        SettingsSection(title = stringResource(R.string.background_tasks_section_recent_title), icon = Icons.Filled.Tune) {
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
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
        state.message?.let {
            Text(
                text = it.asString(),
                color = MaterialTheme.colorScheme.secondary,
                modifier = Modifier.padding(top = 4.dp),
            )
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
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = backgroundTaskTypeLabel(task.taskType),
                style = MaterialTheme.typography.titleSmall,
            )
            Text(
                text = backgroundTaskStatusLabel(task.status),
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
                progress = (task.progressCurrent.toFloat() / task.progressTotal.toFloat())
                    .coerceIn(0f, 1f),
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
            // 后端 error_message 可能是原始异常串 / 英文（str(exc) / "No handler …"），
            // 直出违反 §10。含中文才认为是可读文案直出，否则套泛化文案。
            val genericError = stringResource(R.string.background_tasks_row_error_generic)
            Text(
                text = if (rawError.any { it in '一'..'鿿' }) rawError else genericError,
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
