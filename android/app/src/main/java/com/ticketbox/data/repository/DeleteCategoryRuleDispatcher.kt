package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * ADR-0038 PR-2g.5: replay a queued ``DELETE /api/rules/categories/{id}``
 * call. Companion to [UpdateCategoryRuleDispatcher] and
 * [PatchExpenseDispatcher] — same contract shape, DELETE verb.
 *
 * Target encoding: ``category_rule:<id>`` (same as
 * [UpdateCategoryRuleDispatcher]; the type wireValue disambiguates
 * UPDATE vs DELETE).
 *
 * Payload at enqueue time: [CategoryRuleDeleteRequest] with
 * ``expectedRowVersion`` set to a ``0L`` placeholder (the
 * DTO field is non-nullable Long; row.expectedRowVersion is the
 * single source of truth — round-8 P3#5).
 */
class DeleteCategoryRuleDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<CategoryRuleDeleteRequest>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.DeleteCategoryRule

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val ruleId = parseRuleId(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")

        // ADR-0042: a DeleteCategoryRule row MUST carry an idempotency key
        // (every enqueue mints one). A null key means a malformed / pre-ADR-0042
        // row the server would 422 anyway — surface it as a visible FAILED row
        // the user can drop, not a silent server round-trip + Discard.
        val idempotencyKey = row.idempotencyKey
            ?: return DispatchResult.Failure("DeleteCategoryRule row missing idempotency key")

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
            // ADR-0042: replay carries the row's original intent-time key so a
            // committed-but-unseen first attempt is deduped server-side (HIT)
            // instead of false-409ing on the stale row_version.
            apiProvider(row).deleteCategoryRule(ruleId, request, idempotencyKey)
            // DELETE response carries no body; Success.newRowVersion
            // is null because there's no post-mutation token to
            // cascade (the row is gone).
            DispatchResult.Success(newRowVersion = null)
        } catch (e: HttpException) {
            mapOutboxHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "DELETE category rule threw")
        }
    }

    private fun parseRuleId(targetId: String): Long? {
        val prefix = "category_rule:"
        if (!targetId.startsWith(prefix)) return null
        return targetId.removePrefix(prefix).toLongOrNull()
    }
}
