package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetVoidRequestDto
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException
import java.io.IOException

class CreateExpenseOffsetDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseOffsetCreateRequestDto>,
    private val publishBundle: suspend (String, ExpenseFactBundleDto) -> Unit,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.CreateExpenseOffset

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val expenseRef = parseExpenseTargetRef(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")
        val request = decode(payloadAdapter, row) { it.copy(expectedRowVersion = row.expectedRowVersion) }
            ?: return DispatchResult.Failure("offset create payload is invalid")
        val key = row.idempotencyKey
            ?: return DispatchResult.Failure("CreateExpenseOffset row missing idempotency key")
        return dispatchOffsetCommand {
            val bundle = apiProvider(row).createExpenseOffset(expenseRef, request, key)
            publishBundle(row.ledgerId, bundle)
            DispatchResult.Success(bundle.root.rowVersion)
        }
    }
}

class VoidExpenseOffsetDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseOffsetVoidRequestDto>,
    private val publishBundle: suspend (String, ExpenseFactBundleDto) -> Unit,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.VoidExpenseOffset

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val target = parseExpenseOffsetTargetRef(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")
        val request = decode(payloadAdapter, row) { it.copy(expectedRowVersion = row.expectedRowVersion) }
            ?: return DispatchResult.Failure("offset void payload is invalid")
        val key = row.idempotencyKey
            ?: return DispatchResult.Failure("VoidExpenseOffset row missing idempotency key")
        return dispatchOffsetCommand {
            val bundle = apiProvider(row).voidExpenseOffset(
                target.expenseId.toString(),
                target.offsetPublicId,
                request,
                key,
            )
            publishBundle(row.ledgerId, bundle)
            DispatchResult.Success()
        }
    }
}

private fun <T> decode(adapter: JsonAdapter<T>, row: OutboxRow, freshToken: (T) -> T): T? = try {
    adapter.fromJson(row.payloadJson)?.let(freshToken)
} catch (_: JsonDataException) {
    null
} catch (_: JsonEncodingException) {
    null
}

private suspend fun dispatchOffsetCommand(block: suspend () -> DispatchResult): DispatchResult = try {
    block()
} catch (error: HttpException) {
    mapOffsetHttpException(error)
} catch (error: IOException) {
    DispatchResult.RetryableFailure(error.message ?: "network or cache IO failure")
} catch (cancelled: CancellationException) {
    throw cancelled
} catch (error: Exception) {
    DispatchResult.RetryableFailure(error.message ?: "expense offset publication failed")
}

private fun mapOffsetHttpException(error: HttpException): DispatchResult {
    val body = error.response()?.errorBody()?.string().orEmpty()
    val message = extractOffsetServerMessage(body) ?: error.message().orEmpty()
    return when (error.code()) {
        409 -> when {
            "state_conflict" in body -> DispatchResult.Conflict(message)
            "idempotency_key_in_progress" in body -> DispatchResult.RetryableFailure(message)
            "expense_offset_not_active" in body -> DispatchResult.Discarded(message)
            else -> DispatchResult.Failure(message)
        }
        404 -> DispatchResult.Discarded(message)
        408, 429, in 500..599 -> DispatchResult.RetryableFailure(message)
        else -> DispatchResult.Failure(message.ifEmpty { "HTTP ${error.code()}" })
    }
}

private fun extractOffsetServerMessage(body: String): String? {
    val key = "\"message\":\""
    val start = body.indexOf(key)
    if (start < 0) return null
    val begin = start + key.length
    val end = body.indexOf('"', begin)
    return end.takeIf { it >= 0 }?.let { body.substring(begin, it) }
}
