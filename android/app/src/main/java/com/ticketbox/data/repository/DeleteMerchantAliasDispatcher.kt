package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * ADR-0038 PR-2g.5: replay a queued ``DELETE /api/merchants/aliases/{publicId}``
 * call. Target encoding: ``merchant_alias:<publicId>`` (publicId is
 * a UUID string, not a Long — differs from category_rule's numeric
 * id but follows the same ``<resource>:<id>`` pattern).
 */
class DeleteMerchantAliasDispatcher(
    private val apiProvider: () -> ApiService,
    private val payloadAdapter: JsonAdapter<MerchantAliasDeleteRequest>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.DeleteMerchantAlias

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val publicId = parseAliasPublicId(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")

        // ADR-0042: a DeleteMerchantAlias row MUST carry an idempotency key
        // (every enqueue mints one). A null key means a malformed / pre-ADR-0042
        // row the server would 422 anyway — surface it as a visible FAILED row
        // the user can drop, not a silent server round-trip + Discard.
        val idempotencyKey = row.idempotencyKey
            ?: return DispatchResult.Failure("DeleteMerchantAlias row missing idempotency key")

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
            apiProvider().deleteMerchantAlias(publicId, request, idempotencyKey)
            DispatchResult.Success(newRowVersion = null)
        } catch (e: HttpException) {
            mapHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "DELETE merchant alias threw")
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
