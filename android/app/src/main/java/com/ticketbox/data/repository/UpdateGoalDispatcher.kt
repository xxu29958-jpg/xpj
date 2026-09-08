package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
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
    private val receiptAdapter: JsonAdapter<GoalDto>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.UpdateGoal

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val publicId = parseGoalPublicId(row.targetId)
            ?: return DispatchResult.Failure("原目标无法确认，已保留未发送的修改，请核对。")
        if (row.expectedRowVersion <= 0) return DispatchResult.Failure("原目标版本无法确认，请保留记录并核对。")

        // ADR-0042: an UpdateGoal row MUST carry an idempotency key (every
        // enqueue mints one). A null key means a malformed / pre-ADR-0042 row
        // the server would 422 anyway — surface it as a visible FAILED row the
        // user can drop, not a silent server round-trip + Discard.
        val idempotencyKey = row.idempotencyKey?.takeIf { it.isNotBlank() }
            ?: return DispatchResult.Failure("UpdateGoal row missing idempotency key")

        val request = payloadAdapter.readGoalUpdate(row)
            ?: return DispatchResult.Failure("原修改内容无法读取，已保留记录，请核对。")

        return try {
            // ADR-0042: replay carries the row's original intent-time key, so a
            // committed-but-unseen first attempt is deduped server-side (HIT →
            // canonical row) instead of false-409ing on the stale row_version.
            val updated = apiProvider(row).updateGoal(publicId, request, idempotencyKey, timezone = null)
            if (updated.publicId != publicId || updated.ledgerId != row.ledgerId) {
                DispatchResult.Failure("返回的目标与原提交不匹配，已保留记录。")
            } else DispatchResult.Success(newRowVersion = updated.rowVersion, receiptJson = receiptAdapter.toJson(updated))
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

/** Reads existing flat payloads without changing their durable body or original OCC. */
internal fun JsonAdapter<GoalUpdateRequestDto>.readGoalUpdate(row: OutboxRow): GoalUpdateRequestDto? =
    try {
        fromJson(row.payloadJson)?.takeIf { row.expectedRowVersion > 0 && !row.idempotencyKey.isNullOrBlank() }
            ?.copy(expectedRowVersion = row.expectedRowVersion)
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    }
