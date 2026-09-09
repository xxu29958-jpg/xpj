package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.CategoryRuleDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** All rule mutations replay their captured snapshot; failed admission never settles an unsent command. */
class CategoryRuleDispatcher(
    override val type: PendingMutationType,
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<CategoryRuleSubmissionPayload>,
    private val receiptAdapter: JsonAdapter<CategoryRuleDto>,
) : OutboxMutationDispatcher {
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val payload = runCatching { payloadAdapter.fromJson(row.payloadJson) }.getOrNull()
        if (row.type != type || payload?.supports(row) != true) {
            return DispatchResult.Failure("原规则内容或币种无法确认，已保留原提交，请核对。")
        }
        return try {
            val api = apiProvider(row)
            val key = requireNotNull(row.idempotencyKey)
            if (type == PendingMutationType.DeleteCategoryRule) {
                api.deleteCategoryRule(requireNotNull(row.ruleId()), CategoryRuleDeleteRequest(payload.expectedRowVersion), key)
                DispatchResult.Success()
            } else {
                val accepted = if (type == PendingMutationType.CreateCategoryRule) api.createCategoryRule(payload.request, key)
                    else api.updateCategoryRule(requireNotNull(row.ruleId()), payload.updateRequest(), key)
                if (!payload.acceptsReceipt(row, accepted)) DispatchResult.Failure("返回的规则与原提交不一致，已保留记录。")
                else DispatchResult.Success(newRowVersion = accepted.rowVersion, receiptJson = receiptAdapter.toJson(accepted))
            }
        } catch (error: HttpException) {
            if (error.code() == 404) DispatchResult.Failure("原规则或接口已不可用，已保留原提交，请核对。")
            else mapOutboxHttpException(error)
        } catch (error: IOException) {
            DispatchResult.RetryableFailure(error.message ?: "网络连接中断")
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            DispatchResult.Failure(error.message ?: "规则提交尚未确认")
        }
    }
}
