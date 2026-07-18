package com.ticketbox.ui.screens.tasks

import com.ticketbox.domain.model.BACKGROUND_TASK_RUNNING
import com.ticketbox.domain.model.BackgroundTask
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class BackgroundTaskPresentationTest {
    @Test
    fun cancellableServerTaskStillRequiresWriterPermission() {
        val task = runningTask()

        assertFalse(canCancelBackgroundTask(task = task, canModify = false))
        assertTrue(canCancelBackgroundTask(task = task, canModify = true))
    }

    private fun runningTask(): BackgroundTask = BackgroundTask(
        publicId = "task-1",
        taskType = "csv_import",
        status = BACKGROUND_TASK_RUNNING,
        progressCurrent = 0,
        progressTotal = null,
        progressMessage = null,
        errorCode = null,
        errorMessage = null,
        createdAt = "2026-07-18T08:00:00Z",
        startedAt = null,
        completedAt = null,
        cancellationRequestedAt = null,
    )
}
