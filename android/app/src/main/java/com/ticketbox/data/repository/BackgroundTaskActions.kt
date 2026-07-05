package com.ticketbox.data.repository

import com.ticketbox.domain.model.BackgroundTask

interface BackgroundTaskActions {
    suspend fun fetchBackgroundTasks(): Result<List<BackgroundTask>>
    suspend fun cancelBackgroundTask(publicId: String): Result<BackgroundTask>
}

class ExpenseRepositoryBackgroundTaskActions(
    private val repository: ExpenseRepository,
) : BackgroundTaskActions {
    override suspend fun fetchBackgroundTasks(): Result<List<BackgroundTask>> =
        repository.fetchBackgroundTasks()

    override suspend fun cancelBackgroundTask(publicId: String): Result<BackgroundTask> =
        repository.cancelBackgroundTask(publicId)
}
