package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtRepaymentReceiptDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

class RecordDebtRepaymentDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val adapter: JsonAdapter<DebtRepaymentPayload>,
    private val receiptAdapter: JsonAdapter<DebtRepaymentReceiptDto>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.RecordDebtRepayment

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val intent = row.describeDebtRepayment(adapter).repayment
            ?: return DispatchResult.Failure("debt_repayment_payload_unsupported")
        return try {
            val result = apiProvider(row).recordDebtRepayment(intent.subject.publicId, intent.request, row.idempotencyKey)
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
            when (val result = mapOutboxHttpException(error)) {
                is DispatchResult.Discarded -> DispatchResult.Failure(result.reason)
                else -> result
            }
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("debt_repayment_connection_interrupted")
        } catch (_: RepositoryException) {
            DispatchResult.Failure("debt_repayment_binding_changed")
        } catch (_: Exception) {
            DispatchResult.Failure("debt_repayment_response_unverified")
        }
    }
}
