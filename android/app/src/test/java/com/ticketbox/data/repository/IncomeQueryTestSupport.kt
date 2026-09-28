package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.IncomeQueryCacheDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.remote.dto.IncomePlanDto

/** Pure repository tests use memory; IncomeQueryContinuityRoomTest owns actual disk/transaction proof. */
internal class FakeIncomeQueryCacheDao : IncomeQueryCacheDao {
    private val rows = mutableMapOf<Triple<String, String, String>, StatsProjectionCacheEntity>()
    override suspend fun read(bindingKey: String, kind: String, tag: String) = rows[Triple(bindingKey, kind, tag)]
    override suspend fun barriers(bindingKey: String) = rows.values.filter {
        it.bindingKey == bindingKey && it.kind == "income_write_barrier"
    }.sortedBy { it.tag }
    override suspend fun clearValues(bindingKey: String) {
        rows.entries.removeAll { it.value.bindingKey == bindingKey && it.value.kind in setOf("income_list", "income_history") }
    }
    override suspend fun remove(bindingKey: String, kind: String, tag: String) { rows.remove(Triple(bindingKey, kind, tag)) }
    override suspend fun save(row: StatsProjectionCacheEntity) { rows[Triple(row.bindingKey, row.kind, row.tag)] = row }
}

internal fun testIncomePlanRepository(provider: ApiServiceProvider, outbox: OutboxRepository,
    submissionAdapter: JsonAdapter<IncomePlanSubmissionPayload>, receiptAdapter: JsonAdapter<IncomePlanDto>): IncomePlanRepository =
    IncomePlanRepository(provider, outbox, submissionAdapter, receiptAdapter,
        IncomePlanReadRepository(provider, FakeIncomeQueryCacheDao(), testSnapshotCoordinator(provider, outbox))).also { repository ->
        outbox.onIncomeDispatchPreparing = repository.reads::prepareReadsBeforeDispatch
        outbox.onIncomeDispatchFinished = repository.reads::finishReadDispatch
        outbox.onIncomeAccepted = repository.reads::invalidateReadsAfterAccepted
    }
