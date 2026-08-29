package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

class UpdateRecurringItemDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<RecurringItemUpdateRequestDto>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.UpdateRecurringItem

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val publicId = row.targetId.removePrefix(UPDATE_TARGET_PREFIX).takeIf {
            row.targetId.startsWith(UPDATE_TARGET_PREFIX) && it.isNotBlank()
        } ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")
        val key = row.idempotencyKey
            ?: return DispatchResult.Failure("UpdateRecurringItem row missing idempotency key")
        val request = try {
            val stored = payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
            stored.copy(expectedRowVersion = row.expectedRowVersion)
        } catch (error: JsonDataException) {
            return DispatchResult.Failure("payload JSON shape changed: ${error.message.orEmpty()}")
        } catch (error: JsonEncodingException) {
            return DispatchResult.Failure("payload JSON malformed: ${error.message.orEmpty()}")
        }
        return try {
            val updated = apiProvider(row).updateRecurringItem(publicId, request, key)
            DispatchResult.Success(newRowVersion = updated.rowVersion)
        } catch (error: HttpException) {
            mapRecurringHttpException(error, stateConflictIsResolvable = true)
        } catch (error: IOException) {
            DispatchResult.RetryableFailure(error.message ?: "network IO failure")
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            DispatchResult.Failure(error.message ?: "PATCH recurring item threw")
        }
    }

    private companion object {
        const val UPDATE_TARGET_PREFIX = "recurring_item:"
    }
}
