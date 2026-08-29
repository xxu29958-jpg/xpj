package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
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
        if (!row.targetId.startsWith(CREATE_TARGET_PREFIX)) {
            return DispatchResult.Discarded("invalid target id: ${row.targetId}")
        }
        val key = row.idempotencyKey
            ?: return DispatchResult.Failure("CreateRecurringItem row missing idempotency key")
        val request = try {
            payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
        } catch (error: JsonDataException) {
            return DispatchResult.Failure("payload JSON shape changed: ${error.message.orEmpty()}")
        } catch (error: JsonEncodingException) {
            return DispatchResult.Failure("payload JSON malformed: ${error.message.orEmpty()}")
        }
        return try {
            apiProvider(row).createRecurringItem(request, key)
            DispatchResult.Success()
        } catch (error: HttpException) {
            mapRecurringHttpException(error, stateConflictIsResolvable = false)
        } catch (error: IOException) {
            DispatchResult.RetryableFailure(error.message ?: "network IO failure")
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            DispatchResult.Failure(error.message ?: "POST recurring item threw")
        }
    }

    private companion object {
        const val CREATE_TARGET_PREFIX = "recurring_item_create:"
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
        404 -> DispatchResult.Discarded(message.ifEmpty { "fixed expense no longer exists" })
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
