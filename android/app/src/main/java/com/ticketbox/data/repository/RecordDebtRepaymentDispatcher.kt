package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.DebtRepaymentReceiptDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

class RecordDebtRepaymentDispatcher internal constructor(
    private val guard: LedgerRequestGuard,
    private val adapter: JsonAdapter<DebtRepaymentPayload>,
    private val receiptAdapter: JsonAdapter<DebtRepaymentReceiptDto>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.RecordDebtRepayment

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val intent = row.describeDebtRepayment(adapter).repayment
            ?: return DispatchResult.Failure("debt_repayment_payload_unsupported", definitelyRejected = true)
        return try {
            val result = guard.bind(expectedLedgerId = row.ledgerId).serviceForOriginalDebtWrite(row, intent).recordDebtRepayment(intent.subject.publicId, intent.request, row.idempotencyKey)
            val repaymentId = result.repaymentPublicId
            if (result.debtPublicId != intent.subject.publicId || repaymentId.isNullOrBlank() ||
                result.rowVersion <= intent.expectedRowVersion || result.homeCurrencyCode != intent.subject.homeCurrencyCode) {
                DispatchResult.Failure("debt_repayment_response_unverified")
            } else {
                // A confirmed receipt never lends its fresh OCC to another original command.
                DispatchResult.Success(receiptJson = receiptAdapter.toJson(result))
            }
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            mapDebtWriteHttpException(error, intent.subject.publicId)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("debt_repayment_connection_interrupted")
        } catch (_: RepositoryException) {
            DispatchResult.Failure("debt_repayment_binding_changed", definitelyRejected = true)
        } catch (_: Exception) {
            DispatchResult.Failure("debt_repayment_response_unverified")
        }
    }
}
