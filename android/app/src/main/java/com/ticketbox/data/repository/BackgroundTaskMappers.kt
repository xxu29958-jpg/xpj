package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.domain.model.BackgroundTask

fun BackgroundTaskDto.toDomain(): BackgroundTask = BackgroundTask(
    publicId = publicId,
    taskType = taskType,
    status = status,
    progressCurrent = progressCurrent,
    progressTotal = progressTotal,
    progressMessage = progressMessage,
    errorCode = errorCode,
    errorMessage = errorMessage,
    createdAt = createdAt,
    startedAt = startedAt,
    completedAt = completedAt,
    cancellationRequestedAt = cancellationRequestedAt,
)
