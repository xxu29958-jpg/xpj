package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * ADR-0038 PR-2g.8: replay a queued ``POST /api/expenses/{id}/ocr/retry``.
 * Same token-only shape as [ConfirmExpenseDispatcher]. The re-run OCR
 * returns the refreshed Expense; its ``rowVersion`` cascades onto
 * same-target PENDING rows.
 */
class RetryOcrDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseStateTokenRequest>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.RetryOcr

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val expenseRef = parseExpenseTargetRef(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")

        // ADR-0042: a RetryOcr row MUST carry an idempotency key (every enqueue
        // mints one). A null key means a malformed / pre-ADR-0042 row the server
        // would 422 anyway — surface it as a visible FAILED row the user can
        // drop, not a silent server round-trip + Discard.
        val idempotencyKey = row.idempotencyKey
            ?: return DispatchResult.Failure("RetryOcr row missing idempotency key")

        val request = try {
            val storedPayload = payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
            storedPayload.copy(expectedRowVersion = row.expectedRowVersion)
        } catch (e: JsonDataException) {
            return DispatchResult.Failure(
                "payload JSON shape changed: ${e.message ?: "JsonDataException"}",
            )
        } catch (e: JsonEncodingException) {
            return DispatchResult.Failure(
                "payload JSON malformed: ${e.message ?: "JsonEncodingException"}",
            )
        }

        return try {
            // ADR-0042: replay carries the row's original intent-time key, so a
            // committed-but-unseen first attempt is deduped server-side (HIT →
            // canonical row) instead of false-409ing on the stale row_version.
            val retried = apiProvider(row).retryOcr(expenseRef, request, idempotencyKey)
            DispatchResult.Success(newRowVersion = retried.rowVersion)
        } catch (e: HttpException) {
            mapOutboxHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "POST ocr/retry threw")
        }
    }
}
