package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.DebtDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

class VoidDebtDispatcher internal constructor(private val guard: LedgerRequestGuard,
    private val adapter: JsonAdapter<DebtVoidPayload>, private val receiptAdapter: JsonAdapter<DebtDto>) : OutboxMutationDispatcher {
    override val type = PendingMutationType.VoidDebt
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val intent = row.describeDebtVoid(adapter).debtVoid ?: return DispatchResult.Failure("debt_void_payload_unsupported", definitelyRejected = true)
        return dispatchVoid(intent, row, receiptAdapter, requireVoided = true) {
            guard.bind(expectedLedgerId = row.ledgerId).serviceForOriginalDebtWrite(row, intent).voidDebt(intent.subject.publicId, intent.request, row.idempotencyKey)
        }
    }
}

class VoidDebtRepaymentDispatcher internal constructor(private val guard: LedgerRequestGuard,
    private val adapter: JsonAdapter<DebtRepaymentVoidPayload>, private val receiptAdapter: JsonAdapter<DebtDto>) : OutboxMutationDispatcher {
    override val type = PendingMutationType.VoidDebtRepayment
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val intent = row.describeRepaymentVoid(adapter).repaymentVoid ?: return DispatchResult.Failure("debt_void_payload_unsupported", definitelyRejected = true)
        return dispatchVoid(intent, row, receiptAdapter, requireVoided = false) {
            guard.bind(expectedLedgerId = row.ledgerId).serviceForOriginalDebtWrite(row, intent).voidDebtRepayment(intent.subject.publicId, intent.request, row.idempotencyKey)
        }
    }
}

/** Only the original command's server ACK can settle it; canonical folds never manufacture receipts. */
private suspend fun dispatchVoid(intent: DebtWriteIntent, row: OutboxRow, adapter: JsonAdapter<DebtDto>,
    requireVoided: Boolean, send: suspend () -> DebtDto): DispatchResult = try {
    val result = send()
    if (!result.matchesOriginalVoid(intent, row, requireVoided)) {
        DispatchResult.Failure("debt_void_response_unverified")
    } else DispatchResult.Success(receiptJson = adapter.toJson(result))
} catch (error: CancellationException) {
    throw error
} catch (error: HttpException) {
    when (val result = mapOutboxHttpException(error)) {
        is DispatchResult.Discarded -> DispatchResult.Failure(result.reason, definitelyRejected = true)
        else -> result
    }
} catch (_: IOException) {
    DispatchResult.RetryableFailure("debt_void_connection_interrupted")
} catch (_: RepositoryException) {
    DispatchResult.Failure("debt_void_binding_changed", definitelyRejected = true)
} catch (_: Exception) {
    DispatchResult.Failure("debt_void_response_unverified")
}

private fun DebtDto.matchesOriginalVoid(intent: DebtWriteIntent, row: OutboxRow, requireVoided: Boolean): Boolean {
    val matchesVoidResult = if (requireVoided) status == "voided" && remainingAmountCents == 0L
        else status == "open" && remainingAmountCents > 0L
    return publicId == intent.subject.publicId && ledgerId == row.ledgerId &&
        homeCurrencyCode == intent.subject.homeCurrencyCode && rowVersion == intent.expectedRowVersion + 1 && matchesVoidResult
}
