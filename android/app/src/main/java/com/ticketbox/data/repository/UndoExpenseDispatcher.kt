package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Resume the original Undo; a newer rejection never replaces its reviewed token. */
class UndoExpenseDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseStateTokenRequest>,
    private val publishExpense: suspend (ledgerId: String, expense: ExpenseDto) -> Unit,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.UndoExpense

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val expenseId = parseExpenseTargetRef(row.targetId)?.toLongOrNull()?.takeIf { it > 0 }
            ?: return DispatchResult.Failure("UndoExpense row has invalid target")
        val key = row.idempotencyKey?.takeIf { it.isNotBlank() }
            ?: return DispatchResult.Failure("UndoExpense row missing idempotency key")
        val request = try {
            val payload = payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
            payload.copy(expectedRowVersion = row.expectedRowVersion)
        } catch (error: JsonDataException) {
            return DispatchResult.Failure("payload JSON shape changed: ${error.message}")
        } catch (error: JsonEncodingException) {
            return DispatchResult.Failure("payload JSON malformed: ${error.message}")
        }

        return try {
            val restored = apiProvider(row).undoExpense(expenseId, request, key)
            if (!validExpenseAcceptanceSnapshot(row, restored)) {
                return DispatchResult.Failure(EXPENSE_REJECTION_ORIGINAL_REQUIRES_REVIEW)
            }
            val receipt = expenseAcceptanceReceiptJson(restored)
            publishAcceptedExpense(restored.id, restored.rowVersion) { publishExpense(row.ledgerId, restored) }
                .copy(receiptJson = receipt)
        } catch (error: HttpException) {
            if (error.code() == 404) DispatchResult.Failure("expense_not_found") else mapOutboxHttpException(error)
        } catch (error: IOException) {
            DispatchResult.RetryableFailure(error.message ?: "network IO failure")
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            DispatchResult.Failure(error.message ?: "POST undo expense threw")
        }
    }
}
