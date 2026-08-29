package com.ticketbox.data.repository

import com.ticketbox.domain.model.PendingEnrichmentTask

/** Read-only consumer of the existing durable expense-enrichment task owner. */
interface PendingEnrichmentTaskReader {
    suspend fun fetchPendingEnrichmentTask(publicId: String): Result<PendingEnrichmentTask>
}

internal class ExpensePendingEnrichmentRepository(
    private val core: ExpenseRepositoryCore,
) : PendingEnrichmentTaskReader {
    override suspend fun fetchPendingEnrichmentTask(publicId: String): Result<PendingEnrichmentTask> =
        core.errorHandler.safeCall {
            val bound = core.ledgerRequestGuard.bind()
            bound.call { it.getBackgroundTask(publicId) }.toPendingEnrichmentTask()
        }
}
