package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * ADR-0038 PR-2g reference dispatcher.
 *
 * Replays a queued ``PATCH /api/expenses/{id}`` call. Targets are
 * encoded as ``expense:<id>`` per the outbox convention; the
 * payload is the Moshi-serialised [ExpenseUpdateRequest] minus the
 * token (the token lives on the row's ``expectedRowVersion`` so we
 * can refresh it on KeepMine without re-serialising the whole
 * payload).
 *
 * This is the only dispatcher implemented in PR-2g. The other 15
 * mutation types follow exactly the same shape — each PR-2g
 * follow-up registers one — so a reviewer can extrapolate from
 * this one. Worker wiring + WorkManager scheduler + actual call-
 * site routing live in subsequent PRs.
 *
 * Why ``apiProvider: () -> ApiService`` instead of a captured
 * [ApiService] (PR-2g.2 wiring): the bound ApiService is recreated
 * when the user switches ledger / server. A captured instance would
 * keep dispatching against the previous session and 401 forever
 * after a switch. Resolving the provider at every dispatch call
 * pins the worker to whatever ledger the user is currently on.
 */
class PatchExpenseDispatcher(
    private val apiProvider: () -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseUpdateRequest>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.PatchExpense

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val expenseId = parseExpenseId(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")

        // [codex round-2 P1#3] fix: payload deserialise errors are
        // TERMINAL, not retryable. A corrupted / stale-shape JSON
        // will keep failing on every drain tick if we route it
        // through RetryableFailure; route it through Failure so
        // the user sees the dead row and can drop it.
        val request = try {
            val storedPayload = payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
            // The token on the row is the authoritative one; replace
            // any older value embedded in the serialised payload
            // (KeepMine refreshes ``row.expectedRowVersion`` but
            // doesn't rewrite the serialised payload itself).
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
            val updated = apiProvider().updateExpense(expenseId, request)
            DispatchResult.Success(newRowVersion = updated.rowVersion)
        } catch (e: HttpException) {
            mapHttpException(e)
        } catch (e: IOException) {
            // Network blip / connection reset / read timeout — the
            // server probably never saw the request. Retry on the
            // next drain tick, don't push the user a "失败" banner.
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            // [codex round-2 P1#2] fix: never swallow cancellation;
            // let the engine see it and roll the row back to
            // PENDING in NonCancellable scope.
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "PATCH expense threw")
        }
    }

    private fun mapHttpException(e: HttpException): DispatchResult {
        val body = e.response()?.errorBody()?.string().orEmpty()
        val message = extractServerMessage(body) ?: e.message().orEmpty()
        return when (e.code()) {
            409 -> {
                // ADR-0038 contract: only ``state_conflict`` becomes a
                // user-visible CONFLICT row. Other 409s (e.g.
                // ``items_sum_not_in_mismatch``) are structural and
                // belong in Discarded.
                if ("state_conflict" in body) DispatchResult.Conflict(message)
                else DispatchResult.Discarded(message)
            }
            // [codex finding P1#3] fix: transient server errors are
            // retryable, not terminal. The drain engine puts the
            // row back to PENDING so the next tick gives it another
            // chance.
            in 500..599, 408, 429 -> DispatchResult.RetryableFailure(
                message.ifEmpty { "server ${e.code()}" },
            )
            404, 422 -> DispatchResult.Discarded(message)
            else -> DispatchResult.Failure(message.ifEmpty { "HTTP ${e.code()}" })
        }
    }

    private fun parseExpenseId(targetId: String): Long? {
        val prefix = "expense:"
        if (!targetId.startsWith(prefix)) return null
        return targetId.removePrefix(prefix).toLongOrNull()
    }

    /**
     * Pull the Chinese ``message`` out of the AppError JSON envelope
     * ``{"error":"state_conflict","message":"账单已在其它端被修改"}``.
     * Avoids a heavier Moshi adapter for a one-field probe.
     */
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
