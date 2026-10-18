package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.PaymentCaptureDecisionDto
import com.ticketbox.data.remote.dto.PaymentCaptureDto
import com.ticketbox.data.remote.dto.RepaymentAsExpenseDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

@JsonClass(generateAdapter = true)
data class PaymentCaptureResolution(val revision: Int = 1, val binding: LogicalSessionBinding,
    val publicId: String, val decision: PaymentCaptureDecisionDto? = null,
    val correction: RepaymentAsExpenseDto? = null)

internal object PaymentCaptureWire {
    private val moshi = Moshi.Builder().build()
    val resolution = moshi.adapter(PaymentCaptureResolution::class.java)
    val receipt = moshi.adapter(PaymentCaptureDto::class.java)
}

fun OutboxRow.paymentCaptureReceipt(): PaymentCaptureDto? = runCatching {
    require(type == PendingMutationType.ResolvePaymentCapture)
    PaymentCaptureWire.receipt.fromJson(requireNotNull(receiptJson))
}.getOrNull()

internal fun OutboxRow.paymentResolution(): PaymentCaptureResolution? = runCatching {
    require(type == PendingMutationType.ResolvePaymentCapture && !idempotencyKey.isNullOrBlank())
    val value = requireNotNull(PaymentCaptureWire.resolution.fromJson(payloadJson))
    require(value.revision == 1 && (value.decision == null) != (value.correction == null))
    require(targetId == "${if (value.correction != null) "repayment-draft" else "payment-capture"}:${value.publicId}")
    require(expectedRowVersion == (value.decision?.expectedRowVersion ?: 0L))
    value
}.getOrNull()

internal class PaymentCaptureResolutionDispatcher(private val guard: LedgerRequestGuard,
    private val publish: suspend (LogicalSessionBinding, ExpenseDto) -> Unit) : OutboxMutationDispatcher {
    override val type = PendingMutationType.ResolvePaymentCapture
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Payment capture review")
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val original = row.paymentResolution()
            ?: return DispatchResult.Failure("notification_capture_payload_unsupported", definitelyRejected = true)
        var accepted = false
        return try {
            val bound = guard.bindExact(original.binding)
            val api = bound.serviceFor(requireNotNull(row.bindingOrNull()))
            val result = if (original.correction != null) api.repaymentAsExpense(original.publicId,
                original.correction, requireNotNull(row.idempotencyKey)) else api.decidePaymentCapture(original.publicId,
                requireNotNull(original.decision), requireNotNull(row.idempotencyKey))
            require(result.kind == (original.decision?.kind ?: "expense"))
            accepted = true
            bound.requireStillActive()
            result.expenseId?.let { id ->
                val expense = api.expense(id)
                require(expense.publicId == result.expensePublicId)
                bound.requireStillActive()
                publish(original.binding, expense)
            }
            DispatchResult.Success(receiptJson = PaymentCaptureWire.receipt.toJson(result))
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: HttpException) {
            // A failed projection read cannot turn an accepted command into a rejection.
            // Replaying the retained key obtains the same receipt before publishing again.
            if (accepted || error.code() in 500..599 || error.code() in setOf(408, 429))
                DispatchResult.RetryableFailure("notification_capture_connection_interrupted")
            else DispatchResult.Failure(errors.parseHttpError(error).outboxFailureMessage(),
                definitelyRejected = error.code() in setOf(400, 403, 404, 409, 422), credentialRejected = error.code() == 401)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("notification_capture_connection_interrupted")
        } catch (_: RepositoryException) {
            DispatchResult.RetryableFailure("notification_capture_binding_changed")
        } catch (error: Exception) {
            logNetworkWarning("Payment capture resolution response unverified", error)
            DispatchResult.RetryableFailure("notification_capture_response_unverified")
        }
    }
}
