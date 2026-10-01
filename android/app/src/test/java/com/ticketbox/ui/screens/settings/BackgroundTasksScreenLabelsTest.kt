package com.ticketbox.ui.screens.settings

import com.ticketbox.R
import com.ticketbox.domain.model.BACKGROUND_TASK_CANCELLED
import com.ticketbox.domain.model.BACKGROUND_TASK_COMPLETED
import com.ticketbox.domain.model.BACKGROUND_TASK_FAILED
import com.ticketbox.domain.model.BACKGROUND_TASK_QUEUED
import com.ticketbox.domain.model.BACKGROUND_TASK_RUNNING
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.ui.screens.tasks.backgroundTaskStatusLabelRes
import com.ticketbox.ui.screens.tasks.backgroundTaskTypeLabelRes
import kotlin.test.Test
import kotlin.test.assertEquals

class BackgroundTasksScreenLabelsTest {
    @Test
    fun statusLabelsResolveThroughResources() {
        assertEquals(R.string.background_tasks_status_queued, backgroundTaskStatusLabelRes(BACKGROUND_TASK_QUEUED))
        assertEquals(R.string.background_tasks_status_running, backgroundTaskStatusLabelRes(BACKGROUND_TASK_RUNNING))
        assertEquals(R.string.background_tasks_status_completed, backgroundTaskStatusLabelRes(BACKGROUND_TASK_COMPLETED))
        assertEquals(R.string.background_tasks_status_failed, backgroundTaskStatusLabelRes(BACKGROUND_TASK_FAILED))
        assertEquals(R.string.background_tasks_status_cancelled, backgroundTaskStatusLabelRes(BACKGROUND_TASK_CANCELLED))
        assertEquals(R.string.background_tasks_status_unknown, backgroundTaskStatusLabelRes("server_added_state"))
    }

    @Test
    fun taskTypeLabelsDoNotExposeUnknownBackendTokens() {
        assertEquals(R.string.background_tasks_type_csv_import, backgroundTaskTypeLabelRes("csv_import"))
        assertEquals(
            R.string.background_tasks_type_expense_enrichment,
            backgroundTaskTypeLabelRes("expense_enrichment"),
        )
        assertEquals(R.string.background_tasks_type_unknown, backgroundTaskTypeLabelRes("internal_worker_v2"))
    }

    @Test
    fun summaryModelUsesServerTaskStateWithoutInventingStatus() {
        assertEquals(
            BackgroundTasksSummaryState.Loading,
            backgroundTasksSummaryModel(tasks = emptyList(), loading = true).state,
        )
        assertEquals(
            BackgroundTasksSummaryState.Empty,
            backgroundTasksSummaryModel(tasks = emptyList(), loading = false).state,
        )

        val summary = backgroundTasksSummaryModel(
            tasks = listOf(
                task(BACKGROUND_TASK_QUEUED),
                task(BACKGROUND_TASK_RUNNING, cancellationRequestedAt = "2026-07-03T08:00:00Z"),
                task(BACKGROUND_TASK_FAILED),
                task(BACKGROUND_TASK_COMPLETED),
            ),
            loading = false,
        )

        assertEquals(4, summary.totalCount)
        assertEquals(2, summary.activeCount)
        assertEquals(1, summary.failedCount)
        assertEquals(1, summary.cancellableCount)
        assertEquals(BackgroundTasksSummaryState.Failed, summary.state)
    }

    private fun task(
        status: String,
        cancellationRequestedAt: String? = null,
    ): BackgroundTask = BackgroundTask(
        publicId = "task-$status-${cancellationRequestedAt.orEmpty()}",
        taskType = "csv_import",
        status = status,
        progressCurrent = 0,
        progressTotal = null,
        progressMessage = null,
        errorCode = null,
        errorMessage = null,
        createdAt = "2026-07-03T07:00:00Z",
        startedAt = null,
        completedAt = null,
        cancellationRequestedAt = cancellationRequestedAt,
    )
}
