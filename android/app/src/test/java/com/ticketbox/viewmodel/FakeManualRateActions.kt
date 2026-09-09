package com.ticketbox.viewmodel

import com.ticketbox.data.repository.*
import com.ticketbox.data.remote.dto.*
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow

internal class FakeManualRateActions : ManualRateActions {
    val submissions = MutableStateFlow<List<PendingManualRateSubmission>>(emptyList())
    var currentRates: List<ExchangeRateDto> = emptyList()
    val writes = mutableListOf<Pair<String, ExchangeRateRequestDto>>()
    override fun describeRate(row: OutboxRow) = submissions.value.firstOrNull { it.row.id == row.id }
    override fun observeRates(expectedBinding: LogicalSessionBinding): Flow<List<PendingManualRateSubmission>> = submissions
    override suspend fun recoverRate(expectedBinding: LogicalSessionBinding, pending: PendingManualRateSubmission, drop: Boolean): Result<Unit> =
        Result.success(Unit).also { if (drop) submissions.value = submissions.value.filter { it.row.id != pending.row.id } }
    override suspend fun enqueueRate(expectedBinding: LogicalSessionBinding, month: String, request: ExchangeRateRequestDto,
        originalPublicId: String?): Result<Long> = Result.success(1L).also { writes += month to request }
    override suspend fun exchangeRates(expectedBinding: LogicalSessionBinding, currencyCode: String?,
        homeCurrencyCode: String?, rateDate: String?): Result<List<ExchangeRateDto>> = Result.success(currentRates)
}
