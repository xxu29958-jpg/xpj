package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Draft APIs keep their own fact owners and body idempotency. This dispatcher never confirms a draft. */
internal class NotificationCaptureDispatcher(
    private val guard: LedgerRequestGuard,
    private val onExpense: suspend (LogicalSessionBinding, ExpenseDto) -> Unit,
    private val onRepayment: (LogicalSessionBinding, RepaymentDraftDto) -> Unit,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.CapturePaymentNotification
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Notification capture")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val payload = row.notificationCapture()
            ?: return DispatchResult.Failure("notification_capture_payload_unsupported", definitelyRejected = true)
        return try {
            val bound = guard.bind(expectedLedgerId = row.ledgerId)
            val api = bound.serviceFor(requireNotNull(row.bindingOrNull()))
            val receipt = if (payload.kind == "expense") expense(api, bound, payload)
                else repayment(api, bound, payload)
            DispatchResult.Success(receiptJson = NotificationCaptureWire.receipt.toJson(receipt))
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            classify(error)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("notification_capture_connection_interrupted")
        } catch (_: RepositoryException) {
            // A response may have committed before identity changed. Preserve the original for replay.
            DispatchResult.RetryableFailure("notification_capture_binding_changed")
        } catch (_: Exception) {
            DispatchResult.Failure("notification_capture_response_unverified")
        }
    }

    private suspend fun expense(api: ApiService, bound: BoundLedgerRequest, payload: NotificationCapturePayload): NotificationCaptureReceipt {
        val created = api.createNotificationDraft(payload.expenseRequest())
        require(created.id > 0 && !created.publicId.isNullOrBlank())
        bound.requireStillActive()
        // An idempotent replay may return an already reviewed draft. Publish its current projection,
        // but never recreate a pending state or overwrite its human correction with the captured amount.
        onExpense(bound.logicalBinding, created)
        return NotificationCaptureReceipt(expenseId = created.id)
    }

    private suspend fun repayment(api: ApiService, bound: BoundLedgerRequest, payload: NotificationCapturePayload): NotificationCaptureReceipt {
        val created = api.createRepaymentDraft(payload.repaymentRequest())
        require(created.publicId.isNotBlank())
        bound.requireStillActive()
        onRepayment(bound.logicalBinding, created)
        return NotificationCaptureReceipt(repaymentPublicId = created.publicId)
    }

    private fun classify(error: HttpException): DispatchResult {
        val status = error.code()
        if (status in 500..599 || status in setOf(408, 429)) return DispatchResult.RetryableFailure("notification_capture_connection_interrupted")
        return DispatchResult.Failure(errors.parseHttpError(error).outboxFailureMessage(),
            definitelyRejected = status in setOf(400, 401, 403, 404, 405, 410, 412, 422), credentialRejected = status == 401)
    }
}
