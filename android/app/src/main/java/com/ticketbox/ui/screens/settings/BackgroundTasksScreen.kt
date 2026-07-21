package com.ticketbox.ui.screens.settings

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Tune
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.viewmodel.BackgroundTasksViewModel

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
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        SettingsSection(title = stringResource(R.string.background_tasks_section_recent_title), icon = Icons.Filled.Tune) {
            val summary = remember(state.tasks, state.loading) {
                backgroundTasksSummaryModel(tasks = state.tasks, loading = state.loading)
            }
            BackgroundTasksOverview(summary)
            BackgroundTasksRows(
                tasks = state.tasks,
                loading = state.loading,
                busyTaskId = state.busyTaskId,
                canModify = state.canModify,
                onCancel = viewModel::cancel,
            )
            BackgroundTasksRefreshAction(
                loading = state.loading,
                busy = state.busyTaskId != null,
                onRefresh = viewModel::refresh,
            )
        }
    }
}
