package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Replays one composite confirmed-fact correction and refreshes the Room fact. */
class CorrectExpenseDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseCorrectionRequestDto>,
    private val cacheAuthoritativeExpense: suspend (ledgerId: String, expense: ExpenseDto) -> Unit,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.CorrectExpense

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val expenseRef = parseExpenseTargetRef(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")
        val idempotencyKey = row.idempotencyKey
            ?: return DispatchResult.Failure("CorrectExpense row missing idempotency key")
        val request = try {
            val stored = payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
            stored.copy(expectedRowVersion = row.expectedRowVersion)
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
            val response = apiProvider(row).correctExpense(
                expenseRef,
                request,
                idempotencyKey,
            )
            cacheAuthoritativeExpense(row.ledgerId, response.expense)
            DispatchResult.Success(newRowVersion = response.expense.rowVersion)
        } catch (e: HttpException) {
            mapOutboxHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network or cache IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "POST expense correction threw")
        }
    }
}
