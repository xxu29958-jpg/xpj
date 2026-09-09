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
): DispatchResult {
    val body = error.response()?.errorBody()?.string().orEmpty()
    val message = extractRecurringServerMessage(body) ?: error.message().orEmpty()
    return when (error.code()) {
        409 -> when {
            "idempotency_key_in_progress" in body ->
                DispatchResult.RetryableFailure(message.ifEmpty { "idempotency key in progress" })
            stateConflictIsResolvable && "state_conflict" in body ->
                DispatchResult.Conflict(message.ifEmpty { "fixed expense changed on another device" })
            else -> DispatchResult.Failure(message.ifEmpty { "fixed expense conflict" })
        }
        404 -> DispatchResult.Failure(RECURRING_RECEIPT_UNVERIFIED)
        408, 429, in 500..599 -> DispatchResult.RetryableFailure(
            message.ifEmpty { "server ${error.code()}" },
        )
        else -> DispatchResult.Failure(message.ifEmpty { "HTTP ${error.code()}" })
    }
}

private fun extractRecurringServerMessage(body: String): String? {
    val marker = "\"message\":\""
    val start = body.indexOf(marker)
    if (start < 0) return null
    val begin = start + marker.length
    val end = body.indexOf('"', begin)
    return if (end < 0) null else body.substring(begin, end)
}
