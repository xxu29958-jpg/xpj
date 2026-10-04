package com.ticketbox.ui.screens.settings

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.viewmodel.BackgroundTasksViewModel

@Composable
fun BackgroundTasksScreen(
    viewModel: BackgroundTasksViewModel,
    onBack: () -> Unit,
    onOpenExpense: (Long) -> Unit,
    onOpenConnection: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(state.access?.binding) {
        viewModel.refresh()
    }

    SettingsPageFrame(
        title = stringResource(R.string.background_tasks_page_title),
        subtitle = stringResource(R.string.background_tasks_page_subtitle),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        SettingsSection(title = stringResource(R.string.background_tasks_section_recent_title)) {
            val summary = remember(state.tasks, state.loading) {
                backgroundTasksSummaryModel(tasks = state.tasks, loading = state.loading)
            }
            val failedWithoutData = state.tasks.isEmpty() && !state.loading && state.messageTone == MessageTone.Danger
            if (!failedWithoutData) {
                BackgroundTasksOverview(summary)
                BackgroundTasksRows(
                    state = state,
                    onCancel = viewModel::cancel,
                    onOpenSource = { id -> viewModel.sourceExpenseId(id)?.let(onOpenExpense) },
                )
            }
            BackgroundTasksRefreshAction(
                loading = state.loading,
                busy = state.busyTaskId != null,
                onRefresh = viewModel::refresh,
            )
        }
        SettingsEntryRow(
            title = stringResource(R.string.background_tasks_connection_title),
            subtitle = stringResource(R.string.background_tasks_connection_body),
            icon = Icons.Filled.Wifi,
            onClick = onOpenConnection,
        )
        Text(stringResource(R.string.background_tasks_original_result_title), style = MaterialTheme.typography.titleSmall)
        Text(stringResource(R.string.background_tasks_original_result_body),
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
