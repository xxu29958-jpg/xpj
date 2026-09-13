package com.ticketbox.data.repository

import com.ticketbox.domain.model.BackgroundTask

internal class ExpenseBackgroundTaskRepository(
    private val core: ExpenseRepositoryCore,
) {
    suspend fun fetchBackgroundTasks(binding: LogicalSessionBinding): Result<List<BackgroundTask>> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(binding)
        bound.call { it.listBackgroundTasks() }.items.map { it.toDomain() }
    }

    suspend fun cancelBackgroundTask(binding: LogicalSessionBinding, publicId: String): Result<BackgroundTask> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(binding)
        bound.call { it.cancelBackgroundTask(publicId) }.toDomain()
    }
}
