package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** The only spending-goal POST writer; an unverified response retains the original intent. */
class CreateGoalDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<GoalCreateRequestDto>,
    private val receiptAdapter: JsonAdapter<GoalDto>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.CreateGoal

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val request = payloadAdapter.readGoalCreation(row)?.takeIf { it.isSupportedGoalCreation(row) }
            ?: return DispatchResult.Failure("原创建缺少可确认的金额或币种，已保留记录，请核对。")
        return try {
            val receipt = apiProvider(row).createGoal(request, timezone = null, idempotencyKey = row.idempotencyKey)
            if (request.acceptsGoalCreationReceipt(row, receipt)) {
                DispatchResult.Success(receiptJson = receiptAdapter.toJson(receipt))
            } else DispatchResult.Failure("返回的目标与原创建不匹配，已保留记录。")
        } catch (error: HttpException) {
            when (val result = mapOutboxHttpException(error)) {
                is DispatchResult.Discarded -> DispatchResult.Failure("目标创建未获确认，已保留原提交，请核对。")
                is DispatchResult.Conflict -> DispatchResult.Failure(result.serverMessage)
                else -> result
            }
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("目标创建的连接中断，将继续核对原提交。")
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            DispatchResult.Failure("目标创建的结果无法确认，已保留原提交，请核对。")
        }
    }
}
