package com.ticketbox.data.repository

import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeHistoryPage

/** Canonical income queries do not publish commands or acknowledge an original submission. */
interface IncomePlanReads {
    suspend fun history(binding: LogicalSessionBinding, publicId: String, beforeVersion: Long?): Result<IncomeHistoryPage>
    suspend fun listActive(expectedBinding: LogicalSessionBinding): Result<IncomePlanListing>
    suspend fun listIncluding(expectedBinding: LogicalSessionBinding, status: IncomePlanStatus): Result<List<IncomePlan>>
}

class IncomePlanReadRepository(apiProvider: ApiServiceProvider) : IncomePlanReads {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "IncomePlan")

    override suspend fun history(binding: LogicalSessionBinding, publicId: String, beforeVersion: Long?) = errors.safeCall {
        require(publicId.isNotBlank() && (beforeVersion == null || beforeVersion > 0)) { "收入历史范围不正确。" }
        guard.bindExact(binding).call { api ->
            api.incomePlanHistory(publicId, 20, beforeVersion).also { it.validateIncomeHistory(binding, publicId, beforeVersion) }.toDomain()
        }
    }

    override suspend fun listActive(expectedBinding: LogicalSessionBinding): Result<IncomePlanListing> = errors.safeCall {
        guard.bindExact(expectedBinding).call { api ->
            val response = api.listIncomePlans(status = "active")
            IncomePlanListing(response.items.map { it.toDomain() }, response.expectedAmountCents,
                response.month, response.scheduledAmountCents, response.effectivePlanCount,
                response.homeCurrencyCode, response.missingCurrencyCodes, response.referenceRates.map { it.toDomain() })
        }
    }.onSuccess { listing ->
        onActivePlansSnapshot("m=${listing.month};home=${listing.homeCurrencyCode};total=${listing.expectedAmountCents};" +
            "n=${listing.plans.size};rv=${listing.plans.maxOfOrNull(IncomePlan::rowVersion) ?: 0};" +
            "ua=${listing.plans.maxOfOrNull(IncomePlan::updatedAt).orEmpty()}")
    }

    /** Invalidates advice on a changed confirmed forecast or management snapshot. */
    var onActivePlansSnapshot: (stamp: String) -> Unit = {}

    override suspend fun listIncluding(expectedBinding: LogicalSessionBinding,
        status: IncomePlanStatus): Result<List<IncomePlan>> = errors.safeCall {
        guard.bindExact(expectedBinding).call { it.listIncomePlans(status = status.wireValue).items.map { row -> row.toDomain() } }
    }

}
