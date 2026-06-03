package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * ADR-0038 PR-2g.4: replay a queued ``PATCH /api/rules/categories/{id}``
 * call. Companion to [PatchExpenseDispatcher] — same contract,
 * different target.
 *
 * Target encoding: ``category_rule:<id>`` (numeric id, matches the
 * pattern PatchExpenseDispatcher uses for ``expense:<id>``).
 *
 * Payload: Moshi-serialised [CategoryRuleUpdateRequest] with the
 * token field stripped (the row's ``expectedRowVersion`` is the
 * single source of truth — same shape as the PR-2g.3 round-8 P3#5
 * decision for PatchExpenseDispatcher).
 */
class UpdateCategoryRuleDispatcher(
    private val apiProvider: () -> ApiService,
    private val payloadAdapter: JsonAdapter<CategoryRuleUpdateRequest>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.UpdateCategoryRule

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val ruleId = parseRuleId(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")

        // [codex round-2 P1#3] payload deserialise errors are
        // TERMINAL — see PatchExpenseDispatcher KDoc for the
        // rationale.
        val request = try {
            val storedPayload = payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
            // Row's expectedRowVersion is authoritative. Payload was
            // serialised with expectedRowVersion set to a 0L
            // placeholder at enqueue time (DTO field is non-nullable
            // Long — see [RuleRepository.updateCategoryRuleAllowingOffline]
            // round-8 P3#5: token-out-of-payload, single source of truth).
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
            val updated = apiProvider().updateCategoryRule(ruleId, request)
            DispatchResult.Success(newRowVersion = updated.rowVersion)
        } catch (e: HttpException) {
            mapHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "PATCH category rule threw")
        }
    }

    private fun mapHttpException(e: HttpException): DispatchResult {
        val body = e.response()?.errorBody()?.string().orEmpty()
        val message = extractServerMessage(body) ?: e.message().orEmpty()
        return when (e.code()) {
            409 -> {
                if ("state_conflict" in body) DispatchResult.Conflict(message)
                else DispatchResult.Discarded(message)
            }
            in 500..599, 408, 429 -> DispatchResult.RetryableFailure(
                message.ifEmpty { "server ${e.code()}" },
            )
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
