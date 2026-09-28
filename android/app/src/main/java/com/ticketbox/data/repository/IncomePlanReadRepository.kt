package com.ticketbox.data.repository

import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeHistoryPage
import com.ticketbox.data.local.IncomeQueryCacheDao
import kotlinx.coroutines.flow.Flow

/** Canonical income queries do not publish commands or acknowledge an original submission. */
interface IncomePlanReads {
    val readAccessDenials: Flow<SnapshotAccessDenial>
    suspend fun history(binding: LogicalSessionBinding, publicId: String, beforeVersion: Long?): Result<ReadSnapshot<IncomeHistoryPage>>
    suspend fun listActive(expectedBinding: LogicalSessionBinding): Result<IncomePlanListing>
    suspend fun listIncluding(expectedBinding: LogicalSessionBinding, status: IncomePlanStatus): Result<ReadSnapshot<List<IncomePlan>>>
}

class IncomePlanReadRepository(apiProvider: ApiServiceProvider, cache: IncomeQueryCacheDao,
    coordinator: LocalLedgerSessionCoordinator) : IncomePlanReads {
    internal val queries = IncomeQueryReader(apiProvider, cache, coordinator)
    override val readAccessDenials = queries.accessDenials

    override suspend fun history(binding: LogicalSessionBinding, publicId: String, beforeVersion: Long?) =
        queries.history(binding, publicId, beforeVersion).map { ReadSnapshot(it.value.toDomain(), it.fetchedAt, it.fromCache) }

    internal suspend fun prepareReadsBeforeDispatch(row: OutboxRow) = queries.prepareDispatch(row)
    internal suspend fun finishReadDispatch(row: OutboxRow, result: DispatchResult?) = queries.finishDispatch(row, result)
    internal suspend fun invalidateReadsAfterAccepted(row: OutboxRow) = queries.acceptedDispatch(row)

    override suspend fun listActive(expectedBinding: LogicalSessionBinding): Result<IncomePlanListing> =
        queries.listing(expectedBinding, "active").map { read ->
            val response = read.value
            IncomePlanListing(response.items.map { it.toDomain() }, response.expectedAmountCents,
                response.month, response.scheduledAmountCents, response.effectivePlanCount,
                response.homeCurrencyCode, response.missingCurrencyCodes, response.referenceRates.map { it.toDomain() }, read.fetchedAt, read.fromCache)
    }.onSuccess { listing ->
        if (!listing.fromCache) onActivePlansSnapshot("m=${listing.month};home=${listing.homeCurrencyCode};total=${listing.expectedAmountCents};" +
            "n=${listing.plans.size};rv=${listing.plans.maxOfOrNull(IncomePlan::rowVersion) ?: 0};" +
            "ua=${listing.plans.maxOfOrNull(IncomePlan::updatedAt).orEmpty()}")
    }

    /** Invalidates advice on a changed confirmed forecast or management snapshot. */
    var onActivePlansSnapshot: (stamp: String) -> Unit = {}

    override suspend fun listIncluding(expectedBinding: LogicalSessionBinding,
        status: IncomePlanStatus): Result<ReadSnapshot<List<IncomePlan>>> =
        queries.listing(expectedBinding, status.wireValue).map { read ->
            ReadSnapshot(read.value.items.map { it.toDomain() }, read.fetchedAt, read.fromCache)
        }

}
