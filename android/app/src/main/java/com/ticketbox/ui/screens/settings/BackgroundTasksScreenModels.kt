package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.BACKGROUND_TASK_FAILED
import com.ticketbox.domain.model.BACKGROUND_TASK_QUEUED
import com.ticketbox.domain.model.BACKGROUND_TASK_RUNNING
import com.ticketbox.domain.model.BackgroundTask

internal data class BackgroundTasksSummaryModel(
    val totalCount: Int,
    val activeCount: Int,
    val failedCount: Int,
    val cancellableCount: Int,
    val state: BackgroundTasksSummaryState,
)

internal enum class BackgroundTasksSummaryState {
    Loading,
    Empty,
    Active,
    Failed,
    Settled,
}

internal fun backgroundTasksSummaryModel(
    tasks: List<BackgroundTask>,
    loading: Boolean,
): BackgroundTasksSummaryModel {
    val activeCount = tasks.count { it.status == BACKGROUND_TASK_QUEUED || it.status == BACKGROUND_TASK_RUNNING }
    val failedCount = tasks.count { it.status == BACKGROUND_TASK_FAILED }
    return BackgroundTasksSummaryModel(
        totalCount = tasks.size,
        activeCount = activeCount,
        failedCount = failedCount,
        cancellableCount = tasks.count { it.isCancellable },
        state = when {
            loading && tasks.isEmpty() -> BackgroundTasksSummaryState.Loading
            tasks.isEmpty() -> BackgroundTasksSummaryState.Empty
            failedCount > 0 -> BackgroundTasksSummaryState.Failed
            activeCount > 0 -> BackgroundTasksSummaryState.Active
            else -> BackgroundTasksSummaryState.Settled
        },
    )
}
