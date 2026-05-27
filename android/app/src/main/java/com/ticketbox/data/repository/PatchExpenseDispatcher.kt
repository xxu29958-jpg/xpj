package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import retrofit2.HttpException

/**
 * ADR-0038 PR-2g reference dispatcher.
 *
 * Replays a queued ``PATCH /api/expenses/{id}`` call. Targets are
 * encoded as ``expense:<id>`` per the outbox convention; the
 * payload is the Moshi-serialised [ExpenseUpdateRequest] minus the
 * token (the token lives on the row's ``expectedUpdatedAt`` so we
 * can refresh it on KeepMine without re-serialising the whole
 * payload).
 *
 * This is the only dispatcher implemented in PR-2g. The other 15
 * mutation types follow exactly the same shape — each PR-2g
 * follow-up registers one — so a reviewer can extrapolate from
 * this one. Worker wiring + WorkManager scheduler + actual call-
 * site routing live in subsequent PRs.
 */
class PatchExpenseDispatcher(
    private val api: ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseUpdateRequest>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.PatchExpense

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val expenseId = parseExpenseId(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")
        val storedPayload = payloadAdapter.fromJson(row.payloadJson)
            ?: return DispatchResult.Discarded("payload could not be deserialised")
        // The token on the row is the authoritative one; replace any
        // older value embedded in the serialised payload (KeepMine
        // refreshes ``row.expectedUpdatedAt`` but doesn't rewrite
        // the serialised payload itself).
        val request = storedPayload.copy(expectedUpdatedAt = row.expectedUpdatedAt)
        return try {
            api.updateExpense(expenseId, request)
            DispatchResult.Success
        } catch (e: HttpException) {
            mapHttpException(e)
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
