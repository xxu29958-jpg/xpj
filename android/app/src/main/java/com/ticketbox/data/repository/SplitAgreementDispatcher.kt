package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BillSplitChangeEmptyRequestDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

class SplitAgreementDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val adapter: JsonAdapter<SplitAgreementPayload>,
    private val receiptAdapter: JsonAdapter<SplitAgreementReceipt>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.SplitAgreement

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val intent = adapter.readSplitAgreement(row) ?: return DispatchResult.Failure("split_agreement_payload_unsupported")
        return try {
            val receipt = send(apiProvider(row), intent, row.idempotencyKey)
            // Both original versions belong to this intent; a receipt never cascades a new token.
            DispatchResult.Success(receiptJson = receiptAdapter.toJson(receipt))
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            when (val result = mapOutboxHttpException(error)) {
                is DispatchResult.Discarded -> DispatchResult.Failure(result.reason)
                else -> result
            }
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("split_agreement_connection_interrupted")
        } catch (_: Exception) {
            DispatchResult.Failure("split_agreement_response_unverified")
        }
    }
    private suspend fun send(api: ApiService, intent: SplitAgreementPayload, key: String?): SplitAgreementReceipt {
        val id = intent.originalDebtPublicId
        return when (intent.operation) {
            SPLIT_CREATE -> api.createSplitChangeProposal(id, requireNotNull(intent.create), key)
                .let { SplitAgreementReceipt(it.publicId, it.status) }
            SPLIT_ACCEPT -> api.acceptSplitChangeProposal(id, requireNotNull(intent.proposalPublicId),
                requireNotNull(intent.accept), key).let { SplitAgreementReceipt(it.invitationPublicId, "accepted") }
            SPLIT_REJECT -> api.rejectSplitChangeProposal(id, requireNotNull(intent.proposalPublicId),
                BillSplitChangeEmptyRequestDto(), key).let { SplitAgreementReceipt(it.publicId, it.status) }
            else -> api.withdrawSplitChangeProposal(id, requireNotNull(intent.proposalPublicId),
                BillSplitChangeEmptyRequestDto(), key).let { SplitAgreementReceipt(it.publicId, it.status) }
        }
    }
}
