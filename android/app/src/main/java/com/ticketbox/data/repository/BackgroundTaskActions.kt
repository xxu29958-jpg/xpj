package com.ticketbox.data.repository

import com.ticketbox.domain.model.BackgroundTask

interface BackgroundTaskActions {
    fun canModifyLedger(): Boolean
    suspend fun fetchBackgroundTasks(): Result<List<BackgroundTask>>
    suspend fun cancelBackgroundTask(publicId: String): Result<BackgroundTask>
}

class ExpenseRepositoryBackgroundTaskActions(
    private val repository: ExpenseRepository,
) : BackgroundTaskActions {
    override fun canModifyLedger(): Boolean = repository.canModifyLedger()

    override suspend fun fetchBackgroundTasks(): Result<List<BackgroundTask>> =
        repository.fetchBackgroundTasks()

    override suspend fun cancelBackgroundTask(publicId: String): Result<BackgroundTask> =
        repository.cancelBackgroundTask(publicId)
}
