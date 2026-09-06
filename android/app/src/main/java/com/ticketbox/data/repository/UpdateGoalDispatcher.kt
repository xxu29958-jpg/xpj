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
    private val apiProvider: (OutboxRow) -> ApiService,
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
            val updated = apiProvider(row).updateGoal(publicId, request, idempotencyKey, timezone = null)
            DispatchResult.Success(newRowVersion = updated.rowVersion)
        } catch (e: HttpException) {
            mapOutboxHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "PATCH goal threw")
        }
    }

    private fun parseGoalPublicId(targetId: String): String? {
        val prefix = "goal:"
        if (!targetId.startsWith(prefix)) return null
        val publicId = targetId.removePrefix(prefix)
        return publicId.takeIf { it.isNotBlank() }
    }
}
