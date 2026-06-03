package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * ADR-0038 PR-2g.6: replay a queued ``PATCH /api/merchants/aliases/{publicId}``
 * call. Target encoding: ``merchant_alias:<publicId>`` (mirrors
 * [DeleteMerchantAliasDispatcher] from PR-2g.5).
 *
 * Same contract shape as [UpdateCategoryRuleDispatcher] (PR-2g.4)
 * and [PatchExpenseDispatcher] (PR-2g.3) — PATCH with token-bearing
 * body; HttpException mapping unchanged.
 */
class UpdateMerchantAliasDispatcher(
    private val apiProvider: () -> ApiService,
    private val payloadAdapter: JsonAdapter<MerchantAliasUpdateRequest>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.UpdateMerchantAlias

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val publicId = parseAliasPublicId(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")

        val request = try {
            val storedPayload = payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
            // Row's expectedRowVersion is authoritative. Payload was
            // serialised with a 0L placeholder for the
            // token (DTO field is non-nullable Long; round-8 P3#5
            // single-source-of-truth rule).
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
            val updated = apiProvider().updateMerchantAlias(publicId, request)
            DispatchResult.Success(newRowVersion = updated.rowVersion)
        } catch (e: HttpException) {
            mapHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "PATCH merchant alias threw")
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

    private fun parseAliasPublicId(targetId: String): String? {
        val prefix = "merchant_alias:"
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
