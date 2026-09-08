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
            val result = apiProvider(row).updateIncomePlan(publicId, request, idempotencyKey)
            if (result.publicId != publicId || result.homeCurrencyCode != payload.homeCurrencyCode ||
                result.rowVersion <= row.expectedRowVersion ||
                (request.amountCents != null && result.amountCents != request.amountCents)) {
                return DispatchResult.Failure("无法核对原提交的计划、币种或金额，已保留记录，请核对后继续。")
            }
            DispatchResult.Success()
        } catch (e: HttpException) {
            mapOutboxHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure("连接中断，保留原提交等待重试。")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure("暂时无法确认修改结果，已保留原提交。")
        }
    }
}
