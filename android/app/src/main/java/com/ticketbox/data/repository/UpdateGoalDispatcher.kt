package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * ADR-0042 Slice F: replay a queued ``PATCH /api/goals/{publicId}`` call.
 * Companion to [UpdateCategoryRuleDispatcher] / [UpdateMerchantAliasDispatcher]
 * — same contract (PATCH with token-bearing body), different target.
 *
 * Target encoding: ``goal:<publicId>`` (mirrors ``merchant_alias:<publicId>``).
 *
 * Payload: Moshi-serialised [GoalUpdateRequestDto] with the token field
 * neutralised to 0L at enqueue time — the row's ``expectedRowVersion`` is the
 * single source of truth (round-8 P3#5). The timezone query param is dropped on
 * replay; it only affects the spend-derived fields the server recomputes, not
 * the mutation itself.
 */
class UpdateGoalDispatcher(
    private val apiProvider: () -> ApiService,
    private val payloadAdapter: JsonAdapter<GoalUpdateRequestDto>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.UpdateGoal

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val publicId = parseGoalPublicId(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")

        // ADR-0042: an UpdateGoal row MUST carry an idempotency key (every
        // enqueue mints one). A null key means a malformed / pre-ADR-0042 row
        // the server would 422 anyway — surface it as a visible FAILED row the
        // user can drop, not a silent server round-trip + Discard.
        val idempotencyKey = row.idempotencyKey
            ?: return DispatchResult.Failure("UpdateGoal row missing idempotency key")

        // Payload deserialise errors are TERMINAL — see PatchExpenseDispatcher
        // KDoc for the rationale.
        val request = try {
            val storedPayload = payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
            // Row's expectedRowVersion is authoritative. Payload was serialised
            // with a 0L placeholder for the token (DTO field is non-nullable
            // Long; round-8 P3#5 single-source-of-truth rule).
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
            val updated = apiProvider().updateGoal(publicId, request, idempotencyKey, timezone = null)
            DispatchResult.Success(newRowVersion = updated.rowVersion)
        } catch (e: HttpException) {
            mapHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "PATCH goal threw")
        }
    }

    private fun mapHttpException(e: HttpException): DispatchResult {
        val body = e.response()?.errorBody()?.string().orEmpty()
        val message = extractServerMessage(body) ?: e.message().orEmpty()
        return when (e.code()) {
            409 -> when {
                // ADR-0038 contract: only ``state_conflict`` becomes a
                // user-visible CONFLICT row.
                "state_conflict" in body -> DispatchResult.Conflict(message)
                // ADR-0042: a concurrent same-key request is still mid-flight
                // (claimed, not yet committed). The replay will HIT once it
                // lands — retry on the next tick, don't drop.
                "idempotency_key_in_progress" in body ->
                    DispatchResult.RetryableFailure(message.ifEmpty { "idempotency key in progress" })
                // Other 409s are structural and belong in Discarded.
                else -> DispatchResult.Discarded(message)
            }
            in 500..599, 408, 429 -> DispatchResult.RetryableFailure(
                message.ifEmpty { "server ${e.code()}" },
            )
            // 404: the target row is GONE (deleted / archived-purged / not-found),
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

    private fun parseGoalPublicId(targetId: String): String? {
        val prefix = "goal:"
        if (!targetId.startsWith(prefix)) return null
        val publicId = targetId.removePrefix(prefix)
        return publicId.takeIf { it.isNotBlank() }
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
