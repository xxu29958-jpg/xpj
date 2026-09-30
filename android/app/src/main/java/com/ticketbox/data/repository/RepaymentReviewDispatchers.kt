package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.RepaymentDraftDismissRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

internal class ConfirmRepaymentDraftDispatcher(
    private val guard: LedgerRequestGuard,
    private val payload: JsonAdapter<RepaymentReviewPayload>,
    private val receipt: JsonAdapter<RepaymentDraftDto>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.ConfirmRepaymentDraft

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val original = row.describeRepaymentReview(payload).intent as? RepaymentReviewPayload
            ?: return DispatchResult.Failure("repayment_review_payload_unsupported", definitelyRejected = true)
        return deliverRepaymentReview(original.subject.publicId) {
            val bound = guard.bind(expectedLedgerId = row.ledgerId)
            val result = bound.serviceForOriginalDebtWrite(row, original)
                .confirmRepaymentDraft(original.draftPublicId, original.request, row.idempotencyKey)
            require(result.publicId == original.draftPublicId && result.status == "confirmed" &&
                result.committedDebtPublicId == original.subject.publicId && !result.committedRepaymentPublicId.isNullOrBlank())
            bound.requireStillActive()
            DispatchResult.Success(receiptJson = receipt.toJson(result))
        }
    }
}

internal class DismissRepaymentDraftDispatcher(
    private val guard: LedgerRequestGuard,
    private val payload: JsonAdapter<RepaymentDismissPayload>,
    private val receipt: JsonAdapter<RepaymentDraftDto>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.DismissRepaymentDraft

    override suspend fun dispatch(row: OutboxRow): DispatchResult = deliverRepaymentReview(null) {
        val original = requireNotNull(payload.fromJson(row.payloadJson))
        require(original.revision == 1 && row.targetId == "repayment-draft:${original.draftPublicId}" && !row.idempotencyKey.isNullOrBlank())
        val bound = guard.bindExact(original.binding)
        val result = bound.serviceFor(requireNotNull(row.bindingOrNull()))
            .dismissRepaymentDraft(original.draftPublicId, RepaymentDraftDismissRequestDto())
        require(result.publicId == original.draftPublicId && result.status == "dismissed" && result.committedRepaymentPublicId == null)
        bound.requireStillActive()
        DispatchResult.Success(receiptJson = receipt.toJson(result))
    }
}

private suspend fun deliverRepaymentReview(debtPublicId: String?, call: suspend () -> DispatchResult): DispatchResult = try {
    call()
} catch (error: CancellationException) {
    throw error
} catch (error: HttpException) {
    // A capture 404 is not evidence that its selected Debt vanished.
    mapDebtWriteHttpException(error, debtPublicId.orEmpty())
} catch (_: IOException) {
    DispatchResult.RetryableFailure("repayment_review_connection_interrupted")
} catch (_: RepositoryException) {
    DispatchResult.RetryableFailure("repayment_review_binding_changed")
} catch (_: Exception) {
    DispatchResult.Failure("repayment_review_response_unverified")
}
