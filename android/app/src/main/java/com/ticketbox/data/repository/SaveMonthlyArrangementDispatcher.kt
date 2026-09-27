package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MonthlyArrangementDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Sends only the durable original; HTTP success without a matching receipt is not confirmation. */
class SaveMonthlyArrangementDispatcher(private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<MonthlyArrangementPayload>,
    private val receiptAdapter: JsonAdapter<MonthlyArrangementDto>) : OutboxMutationDispatcher {
    override val type = PendingMutationType.SaveMonthlyArrangement
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val payload = payloadAdapter.readArrangement(row.payloadJson)?.takeIf { it.supports(row) }
            ?: return DispatchResult.Failure("monthly_arrangement_unsupported")
        val request = payload.request.copy(expectedRowVersion = row.expectedRowVersion.takeIf { it > 0 })
        return try {
            val receipt = apiProvider(row).saveMonthlyArrangement(payload.month, request, requireNotNull(row.idempotencyKey))
            if (receipt.ledgerId != row.ledgerId || receipt.month != payload.month ||
                receipt.homeCurrencyCode != request.homeCurrencyCode || receipt.rowVersion != row.expectedRowVersion + 1 ||
                receipt.savingsTargetCents != request.savingsTargetCents || receipt.reservedBufferCents != request.reservedBufferCents)
                DispatchResult.Failure("monthly_arrangement_unverified")
            else DispatchResult.Success(receiptJson = receiptAdapter.toJson(receipt))
        } catch (error: HttpException) {
            mapOutboxHttpException(error).let { if (it is DispatchResult.Discarded) DispatchResult.Failure("monthly_arrangement_unverified") else it }
        } catch (_: IOException) { DispatchResult.RetryableFailure("连接中断，保留原安排提交等待重试。")
        } catch (error: CancellationException) { throw error
        } catch (_: Exception) { DispatchResult.Failure("monthly_arrangement_unverified") }
    }
}
