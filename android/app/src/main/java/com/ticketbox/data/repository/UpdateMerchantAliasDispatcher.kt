package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * ADR-0038 PR-2g.6: replay a queued ``PATCH /api/merchants/aliases/{publicId}``
 * call. Target encoding: ``merchant_alias:<publicId>`` (mirrors
 * [DeleteMerchantAliasDispatcher] from PR-2g.5).
 *
 * Same contract shape as [CategoryRuleDispatcher] (PR-2g.4)
 * and [PatchExpenseDispatcher] (PR-2g.3) — PATCH with token-bearing
 * body; HttpException mapping unchanged.
 */
class UpdateMerchantAliasDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<MerchantAliasUpdateRequest>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.UpdateMerchantAlias

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val publicId = parseAliasPublicId(row.targetId)
            ?: return DispatchResult.Discarded("invalid target id: ${row.targetId}")

        // ADR-0042: an UpdateMerchantAlias row MUST carry an idempotency key
        // (every enqueue mints one). A null key means a malformed / pre-ADR-0042
        // row the server would 422 anyway — surface it as a visible FAILED row
        // the user can drop, not a silent server round-trip + Discard.
        val idempotencyKey = row.idempotencyKey
            ?: return DispatchResult.Failure("UpdateMerchantAlias row missing idempotency key")

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
            // ADR-0042: replay carries the row's original intent-time key, so a
            // committed-but-unseen attempt returns its original accepted version.
            // A peer's newer version must not rebase the next queued intention.
            val updated = apiProvider(row).updateMerchantAlias(publicId, request, idempotencyKey)
            acceptOriginalReceipt(publicId, request.expectedRowVersion, updated)
        } catch (e: HttpException) {
            mapOutboxHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            logNetworkWarning("operation=UpdateMerchantAlias outbox replay failed", e)
            DispatchResult.Failure("商家别名同步暂时失败，请稍后重试。原操作仍保留。")
        }
    }

    private fun acceptOriginalReceipt(publicId: String, expectedRowVersion: Long, receipt: MerchantAliasDto): DispatchResult =
        if (receipt.publicId != publicId || receipt.rowVersion != expectedRowVersion + 1L) {
            logNetworkWarning("operation=UpdateMerchantAlias original receipt mismatch")
            DispatchResult.Failure("原修改回执与原对象或版本不符，请核对商家别名。原操作仍保留。")
        } else {
            DispatchResult.Success(newRowVersion = receipt.rowVersion)
        }

    private fun parseAliasPublicId(targetId: String): String? {
        val prefix = "merchant_alias:"
        if (!targetId.startsWith(prefix)) return null
        val publicId = targetId.removePrefix(prefix)
        return publicId.takeIf { it.isNotBlank() }
    }
}
