package com.ticketbox.ui.screens.settings

import com.ticketbox.R
import com.ticketbox.domain.model.BACKGROUND_TASK_CANCELLED
import com.ticketbox.domain.model.BACKGROUND_TASK_COMPLETED
import com.ticketbox.domain.model.BACKGROUND_TASK_FAILED
import com.ticketbox.domain.model.BACKGROUND_TASK_QUEUED
import com.ticketbox.domain.model.BACKGROUND_TASK_RUNNING
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
        assertEquals(R.string.background_tasks_type_unknown, backgroundTaskTypeLabelRes("internal_worker_v2"))
    }
}
