package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import retrofit2.HttpException

/** Task queries participate in the existing session read barrier; they add no cache. */
internal suspend fun <T> ExpenseRepositoryCore.readBackgroundTask(
    binding: LogicalSessionBinding,
    fetch: suspend (ApiService) -> T,
): Result<T> = errorHandler.safeCall {
    val bound = ledgerRequestGuard.bindExact(binding)
    val ticket = sessionCoordinator.beginSnapshotRead()
    val value = try {
        bound.call { fetch(it) }
    } catch (error: HttpException) {
        val failure = errorHandler.httpFailure(error)
        sessionCoordinator.rejectSnapshotAccess(bound, logicalBindingAdapter.toJson(binding), failure)
        throw failure
    }
    sessionCoordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { value }
}
