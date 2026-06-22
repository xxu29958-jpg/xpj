package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * ADR-0042 Slice E-1 dispatcher: replays a queued ``PUT /api/expenses/{id}/splits``.
 *
 * Body-carrying, same shape as [ReplaceItemsDispatcher]: the payload is the
 * Moshi-serialised [ExpenseSplitReplaceRequestDto] minus the token (the row's
 * ``expectedRowVersion`` is the single source of truth and is copied back over
 * the payload before dispatch, so a KeepMine token refresh doesn't require
 * re-serialising the whole split list).
 *
 * The replace bumps the parent expense's ``row_version`` server-side, and the
 * splits response (ExpenseSplitsResponse) carries that fresh ``row_version`` on
 * the wrapper, so the dispatcher returns it directly as
 * [DispatchResult.Success]'s ``newRowVersion`` — the response is
 * self-describing, no second GET. The drain then cascades it onto a chained
 * same-target PENDING row (e.g. offline splits→confirm) so the follow-up
 * doesn't replay with a stale token and false-409 (ADR-0041 P1).
 */
class ReplaceSplitsDispatcher(
    private val apiProvider: () -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseSplitReplaceRequestDto>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.ReplaceSplits

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val expenseRef = parseExpenseTargetRef(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")

        // ADR-0042: a ReplaceSplits row MUST carry an idempotency key (every
        // enqueue mints one). A null key means a malformed / pre-ADR-0042 row
        // the server would 422 anyway — surface it as a visible FAILED row the
        // user can drop, not a silent server round-trip + Discard.
        val idempotencyKey = row.idempotencyKey
            ?: return DispatchResult.Failure("ReplaceSplits row missing idempotency key")

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
            // ADR-0042: replay carries the row's original intent-time key, so a
            // committed-but-unseen first attempt is deduped server-side (HIT →
            // canonical splits) instead of false-409ing on the stale row_version.
            val response = apiProvider().replaceExpenseSplits(expenseRef, request, idempotencyKey)
            DispatchResult.Success(newRowVersion = response.rowVersion)
        } catch (e: HttpException) {
            mapHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "replace splits threw")
        }
    }

    private fun mapHttpException(e: HttpException): DispatchResult {
        val body = e.response()?.errorBody()?.string().orEmpty()
        val message = extractServerMessage(body) ?: e.message().orEmpty()
        return when (e.code()) {
            409 -> when {
                // Only state_conflict becomes a user-visible CONFLICT row.
                "state_conflict" in body -> DispatchResult.Conflict(message)
                // ADR-0042: a concurrent same-key request is still mid-flight
                // (claimed, not yet committed). The replay will HIT once it
                // lands — retry on the next tick, don't drop.
                "idempotency_key_in_progress" in body ->
                    DispatchResult.RetryableFailure(message.ifEmpty { "idempotency key in progress" })
                // Other (structural) 409s (e.g. splits validation) are terminal.
                else -> DispatchResult.Discarded(message)
            }
            in 500..599, 408, 429 -> DispatchResult.RetryableFailure(message.ifEmpty { "server ${e.code()}" })
            // 404: the target row is GONE (deleted / rejected / not-found),
            // so the mutation is moot — silent discard is correct.
            404 -> DispatchResult.Discarded(message)
            // 422: a validation / payload-contract rejection (invalid_request,
            // malformed body, constraint violation, idempotency_key_reused).
            // It will never succeed on retry, but the user MUST see it —
            // surface a visible FAILED row, not a silent Discard that drops
            // their offline edit.
            422 -> DispatchResult.Failure(message)
            else -> DispatchResult.Failure(message.ifEmpty { "HTTP ${e.code()}" })
        }
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
