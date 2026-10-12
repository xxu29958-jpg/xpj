package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BillSplitAcceptRequestDto
import com.ticketbox.data.remote.dto.BillSplitInboxDto
import java.io.IOException
import retrofit2.HttpException

/** The existing invitation command is replayed from its immutable Room acceptance. */
class AcceptBillSplitDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<BillSplitAcceptPayload>,
    private val receiptAdapter: JsonAdapter<BillSplitInboxDto>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.AcceptBillSplitInvitation
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Accept split")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val original = payloadAdapter.readAcceptance(row) ?: return DispatchResult.Failure("bill_split_accept_payload_unsupported", definitelyRejected = true)
        return try {
            val receipt = apiProvider(row).acceptBillSplitInvitation(original.publicId, BillSplitAcceptRequestDto(original.targetLedgerId))
            if (!receipt.accepts(original)) {
                DispatchResult.Failure("bill_split_accept_response_unverified")
            } else DispatchResult.Success(receiptJson = receiptAdapter.toJson(receipt))
        } catch (error: HttpException) {
            val parsed = errors.parseHttpError(error)
            when {
                parsed.errorCode in setOf("state_conflict", "invitation_not_acceptable", "invitation_expired") ->
                    DispatchResult.Failure("bill_split_accept_requires_review", definitelyRejected = true)
                error.code() in 500..599 || error.code() in setOf(408, 429) -> DispatchResult.RetryableFailure(parsed.message)
                else -> DispatchResult.Failure(parsed.outboxFailureMessage(), definitelyRejected = error.code() in 400..499,
                    credentialRejected = error.code() == 401)
            }
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("bill_split_accept_connection_interrupted")
        }
    }
}
