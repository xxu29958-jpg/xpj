package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * ADR-0030 background_tasks DTOs. Single response shape covers every
 * task_type; ``resultSummary`` is a free-form JSON object whose shape
 * depends on the type (csv_import returns ``rows_imported`` / ``errors``).
 *
 * Mirror of ``backend/app/schemas/_background_task.py``.
 */
data class BackgroundTaskDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "task_type")
    val taskType: String,
    val status: String,
    @param:Json(name = "progress_current")
    val progressCurrent: Int = 0,
    @param:Json(name = "progress_total")
    val progressTotal: Int? = null,
    @param:Json(name = "progress_message")
    val progressMessage: String? = null,
    @param:Json(name = "error_code")
    val errorCode: String? = null,
    @param:Json(name = "error_message")
    val errorMessage: String? = null,
    @param:Json(name = "result_summary")
    val resultSummary: Map<String, Any?>? = null,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "started_at")
    val startedAt: String? = null,
    @param:Json(name = "completed_at")
    val completedAt: String? = null,
    @param:Json(name = "last_progress_at")
    val lastProgressAt: String? = null,
    @param:Json(name = "cancellation_requested_at")
    val cancellationRequestedAt: String? = null,
)

data class BackgroundTaskListResponseDto(
    val items: List<BackgroundTaskDto> = emptyList(),
)
