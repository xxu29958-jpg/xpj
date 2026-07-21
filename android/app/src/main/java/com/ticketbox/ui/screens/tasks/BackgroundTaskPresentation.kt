package com.ticketbox.ui.screens.tasks

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.BACKGROUND_TASK_CANCELLED
import com.ticketbox.domain.model.BACKGROUND_TASK_COMPLETED
import com.ticketbox.domain.model.BACKGROUND_TASK_FAILED
import com.ticketbox.domain.model.BACKGROUND_TASK_QUEUED
import com.ticketbox.domain.model.BACKGROUND_TASK_RUNNING
import com.ticketbox.domain.model.BackgroundTask

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

internal fun canCancelBackgroundTask(
    task: BackgroundTask,
    canModify: Boolean,
): Boolean = canModify && task.isCancellable
