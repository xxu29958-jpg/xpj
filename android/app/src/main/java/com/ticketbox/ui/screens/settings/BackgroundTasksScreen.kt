package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Tune
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.BACKGROUND_TASK_CANCELLED
import com.ticketbox.domain.model.BACKGROUND_TASK_COMPLETED
import com.ticketbox.domain.model.BACKGROUND_TASK_FAILED
import com.ticketbox.domain.model.BACKGROUND_TASK_QUEUED
import com.ticketbox.domain.model.BACKGROUND_TASK_RUNNING
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
