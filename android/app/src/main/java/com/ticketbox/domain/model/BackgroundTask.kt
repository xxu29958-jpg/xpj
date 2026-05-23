package com.ticketbox.domain.model

/**
 * ADR-0030 background_tasks domain model.
 *
 * Status values mirror backend ``BackgroundTaskStatus``. We don't model
 * them as an enum yet because new task_types may add states without
 * breaking older clients — Kotlin sealed-class enforcement would force
 * a rebuild for every new state. String compares against the constants
 * below are deliberate.
 */
data class BackgroundTask(
    val publicId: String,
    val taskType: String,
    val status: String,
    val progressCurrent: Int,
    val progressTotal: Int?,
    val progressMessage: String?,
    val errorCode: String?,
    val errorMessage: String?,
    val createdAt: String,
    val startedAt: String?,
    val completedAt: String?,
    val cancellationRequestedAt: String?,
) {
    val isCancellable: Boolean
        get() = status in setOf(BACKGROUND_TASK_QUEUED, BACKGROUND_TASK_RUNNING) &&
            cancellationRequestedAt == null

    val isTerminal: Boolean
        get() = status in setOf(
            BACKGROUND_TASK_COMPLETED,
            BACKGROUND_TASK_FAILED,
            BACKGROUND_TASK_CANCELLED,
        )
}

const val BACKGROUND_TASK_QUEUED = "queued"
const val BACKGROUND_TASK_RUNNING = "running"
const val BACKGROUND_TASK_COMPLETED = "completed"
const val BACKGROUND_TASK_FAILED = "failed"
const val BACKGROUND_TASK_CANCELLED = "cancelled"

fun backgroundTaskStatusLabel(status: String): String = when (status) {
    BACKGROUND_TASK_QUEUED -> "排队中"
    BACKGROUND_TASK_RUNNING -> "运行中"
    BACKGROUND_TASK_COMPLETED -> "已完成"
    BACKGROUND_TASK_FAILED -> "失败"
    BACKGROUND_TASK_CANCELLED -> "已取消"
    else -> status
}

fun backgroundTaskTypeLabel(taskType: String): String = when (taskType) {
    "csv_import" -> "CSV 导入"
    "v1_migration" -> "v1.0 数据迁移"
    else -> taskType
}
