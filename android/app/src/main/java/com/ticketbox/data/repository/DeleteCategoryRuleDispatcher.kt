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
    private val apiProvider: () -> ApiService,
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
            apiProvider().deleteCategoryRule(ruleId, request, idempotencyKey)
            // DELETE response carries no body; Success.newRowVersion
            // is null because there's no post-mutation token to
            // cascade (the row is gone).
            DispatchResult.Success(newRowVersion = null)
        } catch (e: HttpException) {
            mapHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "DELETE category rule threw")
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
            // 404 on DELETE means "already gone" — the row's intent
            // is satisfied either way, so silently discard.
            404, 422 -> DispatchResult.Discarded(message)
            else -> DispatchResult.Failure(message.ifEmpty { "HTTP ${e.code()}" })
        }
    }

    private fun parseRuleId(targetId: String): Long? {
        val prefix = "category_rule:"
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
