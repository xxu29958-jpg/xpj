package com.ticketbox.data.repository

import com.ticketbox.domain.model.BackgroundTask

internal class ExpenseBackgroundTaskRepository(
    private val core: ExpenseRepositoryCore,
) {
    suspend fun fetchBackgroundTasks(): Result<List<BackgroundTask>> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.listBackgroundTasks() }.items.map { it.toDomain() }
    }

    suspend fun cancelBackgroundTask(publicId: String): Result<BackgroundTask> {
        if (!core.canModifyLedger()) {
            return Result.failure(RepositoryException(BACKGROUND_TASK_VIEWER_READONLY))
        }
        return core.errorHandler.safeCall {
            val bound = core.ledgerRequestGuard.bind()
            bound.call { it.cancelBackgroundTask(publicId) }.toDomain()
        }
    }
}

private const val BACKGROUND_TASK_VIEWER_READONLY = "当前角色为只读，无法取消任务。"
