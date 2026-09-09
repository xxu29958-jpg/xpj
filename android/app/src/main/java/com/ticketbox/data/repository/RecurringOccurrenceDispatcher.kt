package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

class RecurringOccurrenceDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<RecurringOccurrencePayload>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.SetRecurringOccurrencePayment
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Recurring occurrence")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val key = row.idempotencyKey?.takeIf { it.isNotBlank() }
            ?: return DispatchResult.Failure("recurring_occurrence_intent_invalid")
        val payload = payloadAdapter.readSupportedOccurrence(row.payloadJson)
            ?: return DispatchResult.Failure("recurring_occurrence_payload_unsupported")
        if (!payload.matchesOriginal(row)) return DispatchResult.Failure("recurring_occurrence_intent_invalid")
        return try {
            val receipt = apiProvider(row).setRecurringOccurrencePayment(payload.seriesPublicId, payload.period, payload.request, key)
            // Preserve every original command's OCC, including later commands. Never rewrite its frozen payload.
            if (payload.acceptsReceipt(receipt)) DispatchResult.Success()
            else DispatchResult.Failure("recurring_occurrence_response_unverified")
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            classify(error)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("recurring_occurrence_connection_interrupted")
        } catch (_: Exception) {
            DispatchResult.Failure("recurring_occurrence_response_unverified")
        }
    }

    private fun classify(error: HttpException): DispatchResult {
        val parsed = errors.parseHttpError(error)
        val code = parsed.errorCode
        return when {
            code == "idempotency_key_in_progress" ->
                DispatchResult.RetryableFailure("recurring_occurrence_response_pending")
            error.code() == 409 && code in setOf("state_conflict", "recurring_item_archived") ->
                DispatchResult.Conflict("请刷新本期期次与付款，核对后放弃旧提交，再重新选择。")
            error.code() == 409 -> DispatchResult.Failure(parsed.outboxFailureMessage())
            error.code() == 408 || error.code() == 429 || error.code() in 500..599 ->
                DispatchResult.RetryableFailure("recurring_occurrence_connection_interrupted")
            else -> DispatchResult.Failure("recurring_occurrence_rejected")
        }
    }
}
