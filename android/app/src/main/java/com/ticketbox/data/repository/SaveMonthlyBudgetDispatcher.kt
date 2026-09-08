package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Only this owner sends the original durable monthly-budget command. */
class SaveMonthlyBudgetDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<BudgetSavePayload>,
    private val receiptAdapter: JsonAdapter<BudgetMonthlyDto>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.SaveMonthlyBudget

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val key = row.idempotencyKey?.takeIf(String::isNotBlank)
            ?: return DispatchResult.Failure("原预算提交缺少标识，已保留记录，请核对。")
        val payload = payloadAdapter.readSupportedBudgetSave(row.payloadJson)
            ?: return DispatchResult.Failure("原预算提交的格式或币种无法确认，已保留记录，请核对。")
        if (row.targetId != monthlyBudgetTarget(payload.month) || row.expectedRowVersion < 0) {
            return DispatchResult.Failure("原提交与预算月份不匹配，已保留记录，请核对。")
        }
        val request = payload.request.copy(expectedRowVersion = row.expectedRowVersion.takeIf { it > 0 })
        return try {
            val receipt = apiProvider(row).updateMonthlyBudget(payload.month, request, payload.timezone, key)
            if (!receipt.confirms(row, payload.month, request)) {
                DispatchResult.Failure("无法核对原提交的预算、币种或金额，已保留记录，请核对后继续。")
            } else { DispatchResult.Success(receiptJson = receiptAdapter.toJson(receipt)) }
        } catch (error: HttpException) { mapOutboxHttpException(error)
        } catch (_: IOException) { DispatchResult.RetryableFailure("连接中断，保留原预算提交等待重试。")
        } catch (error: CancellationException) { throw error
        } catch (_: Exception) { DispatchResult.Failure("暂时无法确认保存结果，已保留原预算提交。") }
    }
}

private fun BudgetMonthlyDto.confirms(row: OutboxRow, expectedMonth: String, request: BudgetMonthlyUpdateRequestDto): Boolean =
    configured && ledgerId == row.ledgerId && month == expectedMonth && homeCurrencyCode == request.homeCurrencyCode &&
        rowVersion == row.expectedRowVersion + 1 && totalAmountCents == request.totalAmountCents &&
        rolloverAmountCents == request.rolloverAmountCents && nonMonthlyAmountCents == request.nonMonthlyAmountCents &&
        excludedCategories.toSet() == request.excludedCategories.toSet() &&
        categoryBudgets.associate { it.category to it.amountCents } == request.categoryBudgets.associate { it.category to it.amountCents }
