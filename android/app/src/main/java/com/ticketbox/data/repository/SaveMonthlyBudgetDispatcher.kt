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
            ?: return DispatchResult.Failure(BUDGET_SAVE_UNSUPPORTED)
        val payload = payloadAdapter.readSupportedBudgetSave(row.payloadJson)
            ?: return DispatchResult.Failure(BUDGET_SAVE_UNSUPPORTED)
        if (!payload.matches(row)) {
            return DispatchResult.Failure(BUDGET_SAVE_UNSUPPORTED)
        }
        val request = payload.request.copy(expectedRowVersion = row.expectedRowVersion.takeIf { it > 0 })
        return try {
            val receipt = apiProvider(row).updateMonthlyBudget(payload.month, request, payload.timezone, key)
            if (!receipt.confirms(row, payload.month, request)) {
                DispatchResult.Failure(BUDGET_SAVE_UNVERIFIED)
            } else { DispatchResult.Success(receiptJson = receiptAdapter.toJson(receipt)) }
        } catch (error: HttpException) {
            // A month without a budget returns an unconfigured response, never 404.
            // A missing route or ledger does not prove this original was accepted.
            mapOutboxHttpException(error).let { result ->
                if (result is DispatchResult.Discarded) DispatchResult.Failure(BUDGET_SAVE_UNVERIFIED) else result
            }
        } catch (_: IOException) { DispatchResult.RetryableFailure("连接中断，保留原预算提交等待重试。")
        } catch (error: CancellationException) { throw error
        } catch (_: Exception) { DispatchResult.Failure(BUDGET_SAVE_UNVERIFIED) }
    }
}

private fun BudgetMonthlyDto.confirms(row: OutboxRow, expectedMonth: String, request: BudgetMonthlyUpdateRequestDto): Boolean =
    configured && ledgerId == row.ledgerId && month == expectedMonth && homeCurrencyCode == request.homeCurrencyCode &&
        rowVersion == row.expectedRowVersion + 1 && totalAmountCents == request.totalAmountCents &&
        rolloverAmountCents == request.rolloverAmountCents && nonMonthlyAmountCents == request.nonMonthlyAmountCents &&
        excludedCategories.toSet() == request.excludedCategories.toSet() &&
        categoryBudgets.associate { it.category to it.amountCents } == request.categoryBudgets.associate { it.category to it.amountCents }
