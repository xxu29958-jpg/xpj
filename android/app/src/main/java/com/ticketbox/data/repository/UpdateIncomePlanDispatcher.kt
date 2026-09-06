package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Sole network writer for a durable, month-bearing income edit. */
class UpdateIncomePlanDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<IncomePlanEditPayload>,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.UpdateIncomePlan

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val idempotencyKey = row.idempotencyKey?.takeIf { it.isNotBlank() }
            ?: return DispatchResult.Failure("原提交缺少标识，请保留记录并核对计划。")
        val payload = payloadAdapter.readSupportedIncomeEdit(row.payloadJson)
            ?: return DispatchResult.Failure("原提交的月份或格式无法确认，已保留记录，请核对后重新编辑。")
        if (row.targetId != incomePlanTarget(payload.planPublicId) || row.expectedRowVersion <= 0) {
            return DispatchResult.Failure("原提交与计划不匹配，请保留记录并核对。")
        }
        val request = payload.request.copy(expectedRowVersion = row.expectedRowVersion)
        val publicId = payload.planPublicId

        return try {
            // ADR-0042: replay carries the row's original intent-time key, so a
            // committed-but-unseen first attempt is deduped server-side (HIT →
            // original stable result) instead of false-409ing on the stale row_version.
            apiProvider(row).updateIncomePlan(publicId, request, idempotencyKey)
            DispatchResult.Success()
        } catch (e: HttpException) {
            mapHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure("连接中断，保留原提交等待重试。")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure("暂时无法确认修改结果，已保留原提交。")
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
            // 404: the target row is GONE (archived-purged / not-found), so the
            // mutation is moot — silent discard is correct.
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
