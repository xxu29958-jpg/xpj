package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** The only network owner for creating a split invitation. */
class CreateBillSplitDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<BillSplitCreatePayload>,
    private val receiptAdapter: JsonAdapter<com.ticketbox.data.remote.dto.BillSplitSentDto>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.CreateBillSplitInvitation
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Bill split")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val key = row.idempotencyKey?.takeIf { it.isNotBlank() }
            ?: return DispatchResult.Failure("bill_split_intent_invalid")
        val payload = payloadAdapter.readBillSplitIntent(row)
            ?: return DispatchResult.Failure("bill_split_payload_unsupported")
        return try {
            val sent = apiProvider(row).createBillSplitInvitation(payload.expenseId, payload.request, key)
            if (sent.senderExpenseId != payload.expenseId || sent.receiverAccountId != payload.request.receiverAccountId ||
                sent.amountCents != payload.request.amountCents || sent.homeCurrencyCode != payload.homeCurrencyCode) {
                DispatchResult.Failure("bill_split_response_unverified")
            } else DispatchResult.Success(receiptJson = receiptAdapter.toJson(sent))
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            classifyHttpError(error)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("bill_split_connection_interrupted")
        } catch (_: Exception) {
            DispatchResult.Failure("bill_split_response_unverified")
        }
    }

    private fun classifyHttpError(error: HttpException): DispatchResult {
        val parsed = errors.parseHttpError(error)
        return when {
            parsed.errorCode == "state_conflict" -> DispatchResult.Failure("bill_split_requires_review")
            parsed.errorCode == "idempotency_key_in_progress" || error.code() in 500..599 ||
                error.code() == 408 || error.code() == 429 -> DispatchResult.RetryableFailure(parsed.message)
            else -> DispatchResult.Failure(parsed.outboxFailureMessage())
        }
    }
}
