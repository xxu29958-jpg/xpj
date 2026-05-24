package com.ticketbox.data.repository

import com.ticketbox.domain.model.BackgroundTask

internal class ExpenseBackgroundTaskRepository(
    private val core: ExpenseRepositoryCore,
) {
    suspend fun fetchBackgroundTasks(): Result<List<BackgroundTask>> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.listBackgroundTasks() }.items.map { it.toDomain() }
    }

    suspend fun cancelBackgroundTask(publicId: String): Result<BackgroundTask> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.cancelBackgroundTask(publicId) }.toDomain()
    }
}
