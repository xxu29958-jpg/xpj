package com.ticketbox.ui.screens.inbox

import com.ticketbox.R
import com.ticketbox.domain.model.BACKGROUND_TASK_RUNNING
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.BackgroundTasksUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class InboxProcessingScreenModelsTest {
    @Test
    fun initialRequestUsesLoadingStateWithoutInventingRows() {
        val presentation = inboxProcessingPresentation(
            BackgroundTasksUiState(loading = true),
        )

        assertEquals(InboxProcessingBodyState.Loading, presentation.bodyState)
        assertFalse(presentation.refreshingWithRows)
        assertFalse(presentation.showInlineStatus)
    }

    @Test
    fun initialFailureIsAnErrorInsteadOfAnEmptyState() {
        val presentation = inboxProcessingPresentation(
            BackgroundTasksUiState(
                message = UiText.res(R.string.background_tasks_message_load_failed),
            ),
        )

        assertEquals(InboxProcessingBodyState.LoadFailed, presentation.bodyState)
        assertFalse(presentation.showInlineStatus)
    }

    @Test
    fun settledRequestWithoutServerRecordsUsesEmptyState() {
        val presentation = inboxProcessingPresentation(BackgroundTasksUiState())

        assertEquals(InboxProcessingBodyState.Empty, presentation.bodyState)
    }

    @Test
    fun refreshAndRefreshFailureKeepServerRowsReadable() {
        val task = task()
        val refreshing = inboxProcessingPresentation(
            BackgroundTasksUiState(tasks = listOf(task), loading = true),
        )
        val failed = inboxProcessingPresentation(
            BackgroundTasksUiState(
                tasks = listOf(task),
                message = UiText.res(R.string.background_tasks_message_refresh_failed_with_data),
            ),
        )

        assertEquals(InboxProcessingBodyState.Content, refreshing.bodyState)
        assertTrue(refreshing.refreshingWithRows)
        assertFalse(refreshing.showInlineStatus)
        assertEquals(InboxProcessingBodyState.Content, failed.bodyState)
        assertFalse(failed.refreshingWithRows)
        assertTrue(failed.showInlineStatus)
    }

    private fun task(): BackgroundTask = BackgroundTask(
        publicId = "task-1",
        taskType = "csv_import",
        status = BACKGROUND_TASK_RUNNING,
        progressCurrent = 1,
        progressTotal = 10,
        progressMessage = null,
        errorCode = null,
        errorMessage = null,
        createdAt = "2026-07-18T08:00:00Z",
        startedAt = null,
        completedAt = null,
        cancellationRequestedAt = null,
    )
}
