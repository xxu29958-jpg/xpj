package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
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
        } ?: return DispatchResult.Failure(RECURRING_ORIGINAL_UNSUPPORTED)
        val key = row.idempotencyKey?.takeIf(String::isNotBlank)
            ?: return DispatchResult.Failure(RECURRING_ORIGINAL_UNSUPPORTED)
        val request = runCatching { payloadAdapter.fromJson(row.payloadJson) }.getOrNull()
            ?.takeIf { it.matchesOriginal(row) }
            ?: return DispatchResult.Failure(RECURRING_ORIGINAL_UNSUPPORTED)
        return try {
            val receipt = apiProvider(row).updateRecurringItem(publicId, request, key)
            // Each later original retains its own OCC basis; accepting this one cannot rebase it.
            if (receipt.confirms(row, request)) DispatchResult.Success()
            else DispatchResult.Failure(RECURRING_RECEIPT_UNVERIFIED)
        } catch (error: HttpException) {
            mapRecurringHttpException(error, stateConflictIsResolvable = true)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure(RECURRING_CONNECTION_INTERRUPTED)
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            DispatchResult.Failure(RECURRING_RECEIPT_UNVERIFIED)
        }
    }

    private companion object {
        const val UPDATE_TARGET_PREFIX = "recurring_item:"
    }
}
