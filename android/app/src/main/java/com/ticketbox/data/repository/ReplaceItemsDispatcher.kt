package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * ADR-0038 dispatcher: replays a queued ``PUT /api/expenses/{id}/items``.
 *
 * Body-carrying, same shape as [PatchExpenseDispatcher]: the payload is the
 * Moshi-serialised [ExpenseItemReplaceRequestDto] minus the token (the row's
 * ``expectedRowVersion`` is the single source of truth and is copied back over
 * the payload before dispatch, so a KeepMine token refresh doesn't require
 * re-serialising the whole item list).
 *
 * The replace bumps the parent expense's ``row_version`` server-side, and the
 * items response (ExpenseItemsResponse) now carries that fresh
 * ``row_version`` on the wrapper, so the dispatcher returns it directly as
 * [DispatchResult.Success]'s ``newRowVersion`` — the response is
 * self-describing, no second GET. The drain then cascades it onto a chained
 * same-target PENDING row (e.g. offline items→confirm) so the follow-up
 * doesn't replay with a stale token and false-409 (ADR-0041 P1).
 */
class ReplaceItemsDispatcher(
    private val apiProvider: () -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseItemReplaceRequestDto>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.ReplaceItems

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val expenseId = parseExpenseId(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")

        // Payload deserialise errors are TERMINAL (a corrupted / stale-shape
        // JSON keeps failing every tick) — route through Failure so the user
        // sees the dead row, not RetryableFailure.
        val request = try {
            val storedPayload = payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
            storedPayload.copy(expectedRowVersion = row.expectedRowVersion)
        } catch (e: JsonDataException) {
            return DispatchResult.Failure("payload JSON shape changed: ${e.message ?: "JsonDataException"}")
        } catch (e: JsonEncodingException) {
            return DispatchResult.Failure("payload JSON malformed: ${e.message ?: "JsonEncodingException"}")
        }

        return try {
            val response = apiProvider().replaceExpenseItems(expenseId, request)
            DispatchResult.Success(newRowVersion = response.rowVersion)
        } catch (e: HttpException) {
            mapHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "replace items threw")
        }
    }

    private fun mapHttpException(e: HttpException): DispatchResult {
        val body = e.response()?.errorBody()?.string().orEmpty()
        val message = extractServerMessage(body) ?: e.message().orEmpty()
        return when (e.code()) {
            409 -> {
                // Only state_conflict becomes a user-visible CONFLICT row.
                // Structural 409s (e.g. items_sum validation) are terminal.
                if ("state_conflict" in body) DispatchResult.Conflict(message)
                else DispatchResult.Discarded(message)
            }
            in 500..599, 408, 429 -> DispatchResult.RetryableFailure(message.ifEmpty { "server ${e.code()}" })
            404, 422 -> DispatchResult.Discarded(message)
            else -> DispatchResult.Failure(message.ifEmpty { "HTTP ${e.code()}" })
        }
    }

    private fun parseExpenseId(targetId: String): Long? {
        val prefix = "expense:"
        if (!targetId.startsWith(prefix)) return null
        return targetId.removePrefix(prefix).toLongOrNull()
    }

    private fun extractServerMessage(body: String): String? {
        val key = "\"message\":\""
        val start = body.indexOf(key)
        if (start < 0) return null
        val begin = start + key.length
        val end = body.indexOf('"', begin)
        if (end < 0) return null
        return body.substring(begin, end)
    }
}
