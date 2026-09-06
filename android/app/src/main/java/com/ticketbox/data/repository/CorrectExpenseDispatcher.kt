package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Sole sender of the original, persisted composite correction. */
class CorrectExpenseDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseCorrectionPayload>,
    private val cacheAuthoritativeExpense: suspend (ledgerId: String, expense: ExpenseDto) -> Unit,
    private val onConfirmedCommitted: (ledgerId: String) -> Unit,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.CorrectExpense

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val intent = payloadAdapter.readSupportedCorrection(row)
            ?: return DispatchResult.Failure("correction_requires_review")
        val response = try {
            apiProvider(row).correctExpense(intent.expenseId.toString(), intent.request, requireNotNull(row.idempotencyKey))
        } catch (e: HttpException) {
            val result = mapOutboxHttpException(e)
            return if (result is DispatchResult.Discarded) DispatchResult.Failure("correction_target_unavailable") else result
        } catch (_: IOException) {
            return DispatchResult.RetryableFailure("correction_delivery_unknown")
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            return DispatchResult.Failure("correction_request_failed")
        }
        // A rebuildable cache failure cannot undo a known 2xx. The detail observer
        // retains DONE and independently refreshes fact/collections/history.
        var cancellation: CancellationException? = null
        try {
            cacheAuthoritativeExpense(row.ledgerId, response.expense)
        } catch (e: CancellationException) {
            cancellation = e
        } catch (_: Exception) {
            // The authoritative GET is the recovery path; never resend a new command.
        } finally {
            try {
                onConfirmedCommitted(row.ledgerId)
            } catch (e: CancellationException) {
                cancellation = cancellation ?: e
            } catch (_: Exception) {
                // Notification failure also cannot undo delivery or mask cancellation.
            }
        }
        cancellation?.let { throw it }
        return DispatchResult.Success(newRowVersion = response.expense.rowVersion)
    }
}
