package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.IncomePlanDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Sole create/update writer: only the receipt for the saved command can acknowledge it. */
class IncomePlanDispatcher(
    override val type: PendingMutationType,
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<IncomePlanSubmissionPayload>,
    private val receiptAdapter: JsonAdapter<IncomePlanDto>,
) : OutboxMutationDispatcher {
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val payload = payloadAdapter.readSupportedIncomeSubmission(row.payloadJson)
        if (row.type != type || payload?.supports(row) != true) {
            return DispatchResult.Failure("原收入提交的月份、币种或格式无法确认，已保留记录，请核对。")
        }
        return try {
            val api = apiProvider(row)
            val key = requireNotNull(row.idempotencyKey)
            val result = if (type == PendingMutationType.CreateIncomePlan) api.createIncomePlan(payload.createRequest(), key)
                else api.updateIncomePlan(payload.planPublicId, payload.request.copy(expectedRowVersion = row.expectedRowVersion), key)
            if (!payload.acceptsReceipt(row, result)) DispatchResult.Failure("返回的收入计划与原提交不一致，已保留记录，请核对。")
            else DispatchResult.Success(newRowVersion = result.rowVersion, receiptJson = receiptAdapter.toJson(result))
        } catch (error: HttpException) {
            if (error.code() == 404) DispatchResult.Failure("原收入计划或接口已不可用，已保留原提交，请核对。")
            else mapOutboxHttpException(error)
        } catch (error: IOException) {
            DispatchResult.RetryableFailure("连接中断，保留原提交等待重试。")
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            DispatchResult.Failure("暂时无法确认收入提交结果，已保留原记录。")
        }
    }
}
