package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

class CreateRecurringItemDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<RecurringItemCreateRequestDto>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.CreateRecurringItem

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val key = row.idempotencyKey?.takeIf(String::isNotBlank)
            ?: return DispatchResult.Failure(RECURRING_ORIGINAL_UNSUPPORTED)
        val request = runCatching { payloadAdapter.fromJson(row.payloadJson) }.getOrNull()
            ?.takeIf { it.matchesOriginal(row) }
            ?: return DispatchResult.Failure(RECURRING_ORIGINAL_UNSUPPORTED)
        return try {
            val receipt = apiProvider(row).createRecurringItem(request, key)
            if (receipt.confirms(row, request)) DispatchResult.Success()
            else DispatchResult.Failure(RECURRING_RECEIPT_UNVERIFIED)
        } catch (error: HttpException) {
            mapRecurringHttpException(error, stateConflictIsResolvable = false)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure(RECURRING_CONNECTION_INTERRUPTED)
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            DispatchResult.Failure(RECURRING_RECEIPT_UNVERIFIED)
        }
    }
}

internal fun mapRecurringHttpException(
    error: HttpException,
    stateConflictIsResolvable: Boolean,
): DispatchResult = when (val result = mapOutboxHttpException(error)) {
    is DispatchResult.Discarded -> DispatchResult.Failure(RECURRING_RECEIPT_UNVERIFIED)
    is DispatchResult.Conflict -> if (stateConflictIsResolvable) result else DispatchResult.Failure(result.serverMessage)
    else -> result
}
