package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExchangeRateDto
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException
import java.io.IOException

class ManualExchangeRateDispatcher(private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<ManualRatePayload>, private val receiptAdapter: JsonAdapter<ExchangeRateDto>) : OutboxMutationDispatcher {
    override val type = PendingMutationType.SaveManualExchangeRate
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val payload = runCatching { payloadAdapter.fromJson(row.payloadJson) }.getOrNull()
        if (payload?.supports(row) != true) return DispatchResult.Failure("manual_rate_original_unverified")
        return try {
            val receipt = apiProvider(row).saveExchangeRate(payload.request.currencyCode, payload.request.rateDate,
                payload.request, requireNotNull(row.idempotencyKey))
            if (!payload.accepts(row, receipt)) DispatchResult.Failure("manual_rate_response_unverified")
            else DispatchResult.Success(receiptJson = receiptAdapter.toJson(receipt))
        } catch (error: HttpException) {
            if (error.code() == 404) DispatchResult.Failure("manual_rate_original_unverified") else mapOutboxHttpException(error)
        } catch (error: IOException) {
            DispatchResult.RetryableFailure("network_unavailable")
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            DispatchResult.Failure("manual_rate_response_unverified")
        }
    }
}
