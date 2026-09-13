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
    private val publishAuthoritativeProjection: suspend (row: OutboxRow, expense: ExpenseDto) -> Unit,
    private val onConfirmedCommitted: (ledgerId: String) -> Unit,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.CorrectExpense
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "ExpenseCorrection")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val intent = payloadAdapter.readSupportedCorrection(row)
            ?: return DispatchResult.Failure("correction_requires_review")
        val response = try {
            apiProvider(row).correctExpense(intent.expenseId.toString(), intent.request, requireNotNull(row.idempotencyKey))
        } catch (e: HttpException) {
            return refusal(e)
        } catch (_: IOException) {
            return DispatchResult.RetryableFailure("correction_delivery_unknown")
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            return DispatchResult.Failure("correction_request_failed")
        }
        // A rebuildable cache failure cannot undo a known 2xx. Persist its receipt
        // version with DONE so detail and global recovery can request a fresh root.
        var cancellation: CancellationException? = null
        var cacheRefreshVersion: Long? = null
        try {
            publishAuthoritativeProjection(row, response.expense)
        } catch (e: CancellationException) {
            cancellation = e
        } catch (_: Exception) {
            // The authoritative GET is the recovery path; never resend a new command.
            cacheRefreshVersion = response.expense.rowVersion
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
        return DispatchResult.Success(newRowVersion = response.expense.rowVersion, cacheRefreshVersion = cacheRefreshVersion)
    }

    private fun refusal(error: HttpException): DispatchResult {
        if (error.code() == 422) return DispatchResult.Failure("correction_requires_review")
        val parsed = errors.parseHttpError(error)
        if (error.code() == 409 && parsed.errorCode == CORRECTION_RATE_PENDING) {
            return DispatchResult.Failure(parsed.correctionRateFailure())
        }
        val result = mapOutboxHttpError(error.code(), parsed)
        return if (result is DispatchResult.Discarded) DispatchResult.Failure("correction_target_unavailable") else result
    }
}
