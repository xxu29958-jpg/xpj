package com.ticketbox.viewmodel

import com.ticketbox.domain.model.ExchangeRateRequest
import com.ticketbox.domain.model.ExchangeRate
import com.ticketbox.domain.model.ReferenceRateRequest
import com.ticketbox.domain.model.ReferenceRates
import com.ticketbox.data.repository.*
import com.ticketbox.data.remote.dto.*
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow

internal class FakeManualRateActions : ManualRateActions {
    var reference = ReferenceRates("frankfurter", true, "waiting", items = emptyList())
    override suspend fun referenceRates(expectedBinding: LogicalSessionBinding, request: ReferenceRateRequest,
        fetch: Boolean): Result<ReferenceRates> = Result.success(reference)
    val submissions = MutableStateFlow<List<PendingManualRateSubmission>>(emptyList())
    var currentRates: List<ExchangeRate> = emptyList()
    val writes = mutableListOf<Pair<String, ExchangeRateRequest>>()
    override fun describeRate(row: OutboxRow) = submissions.value.firstOrNull { it.row.id == row.id }
    override fun observeRates(expectedBinding: LogicalSessionBinding): Flow<List<PendingManualRateSubmission>> = submissions
    override suspend fun recoverRate(expectedBinding: LogicalSessionBinding, pending: PendingManualRateSubmission, drop: Boolean): Result<Unit> =
        Result.success(Unit).also { if (drop) submissions.value = submissions.value.filter { it.row.id != pending.row.id } }
    override suspend fun enqueueRate(expectedBinding: LogicalSessionBinding, month: String, request: ExchangeRateRequest,
        originalPublicId: String?): Result<Long> = Result.success(1L).also { writes += month to request }
    override suspend fun exchangeRates(expectedBinding: LogicalSessionBinding, currencyCode: String?,
        homeCurrencyCode: String?, rateDate: String?): Result<List<ExchangeRate>> = Result.success(currentRates)
}
