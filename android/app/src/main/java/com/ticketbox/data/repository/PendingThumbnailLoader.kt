package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit

class PendingThumbnailLoader(
    private val repository: PendingReviewActions,
    private val concurrency: Int = DEFAULT_CONCURRENCY,
) {
    suspend fun loadMissing(
        expenses: List<Expense>,
        existing: Map<Long, ProtectedImage>,
    ): Map<Long, ProtectedImage> = coroutineScope {
        val activeIds = expenses.map { expense -> expense.id }.toSet()
        val missing = expenses.filter { expense ->
            expense.imagePath != null && !existing.containsKey(expense.id)
        }
        if (missing.isEmpty()) return@coroutineScope emptyMap()

        val limiter = Semaphore(concurrency.coerceAtLeast(1))
        missing
            .map { expense ->
                async {
                    limiter.withPermit {
                        repository.fetchThumbnail(expense.id)
                            .getOrNull()
                            ?.let { image -> expense.id to image }
                    }
                }
            }
            .awaitAll()
            .filterNotNull()
            .filter { (id, _) -> id in activeIds }
            .toMap()
    }

    private companion object {
        const val DEFAULT_CONCURRENCY = 4
    }
}
