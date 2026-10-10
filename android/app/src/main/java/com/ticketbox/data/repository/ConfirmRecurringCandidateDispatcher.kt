package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

class ConfirmRecurringCandidateDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<RecurringCandidatePayload>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.ConfirmRecurringCandidate

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val key = row.idempotencyKey?.takeIf(String::isNotBlank)
            ?: return DispatchResult.Failure(RECURRING_ORIGINAL_UNSUPPORTED, definitelyRejected = true)
        val payload = runCatching { payloadAdapter.fromJson(row.payloadJson) }.getOrNull()
            ?.takeIf { it.matchesOriginal(row) }
            ?: return DispatchResult.Failure(RECURRING_ORIGINAL_UNSUPPORTED, definitelyRejected = true)
        return try {
            val receipt = apiProvider(row).confirmRecurringCandidate(payload.request, payload.timezone, key)
            if (receipt.confirms(row, payload)) DispatchResult.Success()
            else {
                logNetworkWarning("operation=ConfirmRecurringCandidate original receipt mismatch")
                DispatchResult.Failure(RECURRING_RECEIPT_UNVERIFIED)
            }
        } catch (error: HttpException) {
            mapRecurringHttpException(error, stateConflictIsResolvable = false)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure(RECURRING_CONNECTION_INTERRUPTED)
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            logNetworkWarning("operation=ConfirmRecurringCandidate outbox replay failed", error)
            DispatchResult.Failure(RECURRING_RECEIPT_UNVERIFIED)
        }
    }
}
