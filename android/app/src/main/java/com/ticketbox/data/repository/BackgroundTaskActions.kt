package com.ticketbox.data.repository

import com.ticketbox.domain.model.BackgroundTask
import kotlinx.coroutines.flow.Flow

interface BackgroundTaskActions {
    fun currentAccess(): LedgerAccessContext?
    fun observeAccess(): Flow<LedgerAccessContext?>
    suspend fun fetchBackgroundTasks(binding: LogicalSessionBinding): Result<List<BackgroundTask>>
    suspend fun cancelBackgroundTask(binding: LogicalSessionBinding, publicId: String): Result<BackgroundTask>
}

class ExpenseRepositoryBackgroundTaskActions(
    private val repository: ExpenseRepository,
) : BackgroundTaskActions {
    override fun currentAccess(): LedgerAccessContext? = repository.captureDeferredLedgerBinding()?.let {
        LedgerAccessContext(it, repository.canModifyLedger())
    }

    override fun observeAccess(): Flow<LedgerAccessContext?> = repository.observeLedgerAccess()

    override suspend fun fetchBackgroundTasks(binding: LogicalSessionBinding): Result<List<BackgroundTask>> =
        repository.fetchBackgroundTasks(binding)

    override suspend fun cancelBackgroundTask(binding: LogicalSessionBinding, publicId: String): Result<BackgroundTask> =
        repository.cancelBackgroundTask(binding, publicId)
}
