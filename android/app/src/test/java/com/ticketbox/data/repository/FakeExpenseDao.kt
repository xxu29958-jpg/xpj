package com.ticketbox.data.repository

import com.ticketbox.data.local.ConfirmedStreamPruneScope
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.local.ExpenseOffsetStreamEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map

internal class FakeExpenseDao(
    private val events: MutableList<String> = mutableListOf(),
    private val monthlyCache: FakeMonthlyArrangementCacheDao = FakeMonthlyArrangementCacheDao(),
) : ExpenseDao {
    override suspend fun clearMonthlyReadSnapshots() = monthlyCache.clearReadSnapshots()
    override suspend fun clearMonthlyReadSnapshotsForBinding(bindingKey: String) = monthlyCache.clearReadSnapshots(bindingKey)
    override suspend fun monthlyReadSnapshotBindings() = monthlyCache.readSnapshotBindings()
    private val statsCache = com.ticketbox.data.local.StatsProjectionCacheFake()
    override suspend fun clearDebtEntrySnapshots(bindingKey: String, publicId: String) {
        statsCache.byKind(bindingKey, "debt_detail").filter { it.tag == publicId }.forEach(statsCache::delete)
        statsCache.byKind(bindingKey, "debt_activity").filter { it.tag.startsWith("$publicId:") }.forEach(statsCache::delete)
    }
    override suspend fun debtAgreementSnapshots(bindingKey: String) = statsCache.byKind(bindingKey, "debt_agreement")
    override suspend fun debtDirectBarriers(bindingKey: String) = statsCache.byKind(bindingKey, "debt_direct_barrier")
    override suspend fun clearDebtDirectBarriers(bindingKey: String, tokens: List<String>) {
        statsCache.byKind(bindingKey, "debt_direct_barrier").filter { it.tag in tokens }.forEach(statsCache::delete)
    }
    override suspend fun debtReadEpoch(bindingKey: String) = statsCache.find(bindingKey, "debt_read_epoch", "", "", "UTC").singleOrNull()?.responseJson
    override suspend fun clearDebtListSnapshots(bindingKey: String) = statsCache.clearKinds(bindingKey, setOf("debt_list"))
    override suspend fun clearDebtSnapshots(bindingKey: String) = statsCache.clearKinds(bindingKey, setOf("debt_list", "debt_detail", "debt_activity", "debt_agreement"))
    override suspend fun debtResourceDenials(bindingKey: String) = statsCache.byKind(bindingKey, "debt_resource_denial")
    override suspend fun clearDebtResourceDenial(bindingKey: String, publicId: String) {
        statsCache.byKind(bindingKey, "debt_resource_denial").filter { it.tag == publicId }.forEach(statsCache::delete)
    }
    private val goalCache = com.ticketbox.data.local.GoalQueryCacheFake()
    override suspend fun recurringReadEpoch(bindingKey: String) =
        statsCache.find(bindingKey, "recurring_read_epoch", "", "", "UTC").singleOrNull()?.responseJson
    override suspend fun clearRecurringSnapshots(bindingKey: String) = statsCache.clearRecurring(bindingKey)
    override suspend fun saveGoalSnapshots(snapshots: List<com.ticketbox.data.local.GoalQueryCacheEntity>) = goalCache.save(snapshots)
    override suspend fun goalSnapshot(bindingKey: String, timezone: String, queryKey: String) = goalCache.find(bindingKey, timezone, queryKey)
    override suspend fun clearGoalSnapshots() = goalCache.clear(null)
    override suspend fun clearGoalSnapshotsForLedger(ledgerId: String) = goalCache.clear(ledgerId)
    override suspend fun clearGoalSnapshotsForBinding(bindingKey: String) = goalCache.clearBinding(bindingKey)
    override suspend fun clearStatsProjectionsForBinding(bindingKey: String) = statsCache.clearBinding(bindingKey)
    override suspend fun budgetSnapshotsForMonth(bindingKey: String, month: String) = statsCache.budgetMonth(bindingKey, month)
    override suspend fun deleteStatsProjection(snapshot: com.ticketbox.data.local.StatsProjectionCacheEntity) = statsCache.delete(snapshot)
    override suspend fun saveStatsProjection(snapshot: com.ticketbox.data.local.StatsProjectionCacheEntity) = statsCache.save(snapshot)
    override suspend fun statsProjections(bindingKey: String, kind: String, month: String, tag: String,
        timezone: String) = statsCache.find(bindingKey, kind, month, tag, timezone)
    override suspend fun clearStatsProjections() = statsCache.clear(null)
    override suspend fun clearStatsProjectionsForLedger(ledgerId: String) = statsCache.clear(ledgerId)

    private val expenses = linkedMapOf<Long, ExpenseEntity>()
    private val flows = mutableMapOf<String, MutableStateFlow<List<ExpenseEntity>>>()
    private val offsets = linkedMapOf<Pair<String, String>, ExpenseOffsetStreamEntity>()
    private val offsetFlows = mutableMapOf<String, MutableStateFlow<List<ExpenseOffsetStreamEntity>>>()
    private var nextId = 1L
    var beforeApplyConfirmedSync: (suspend () -> Unit)? = null
    var onAfterApplyConfirmedSync: (() -> Unit)? = null
    var insertFailure: Throwable? = null

    override fun observeConfirmed(ledgerId: String): Flow<List<ExpenseEntity>> = flowFor(ledgerId)

    override fun observeConfirmedStreamRoots(ledgerId: String): Flow<List<ExpenseEntity>> =
        flowFor(ledgerId).map { rows -> rows.filter(::hasCompleteStreamProjection) }

    override fun observeConfirmedStreamOffsets(ledgerId: String): Flow<List<ExpenseOffsetStreamEntity>> =
        offsetFlowFor(ledgerId)

    override suspend fun getConfirmedStreamOffsets(ledgerId: String): List<ExpenseOffsetStreamEntity> =
        offsetSnapshot(ledgerId)

    override suspend fun confirmedStreamOffsetPublicIdsForLedger(ledgerId: String): List<String> =
        offsetSnapshot(ledgerId).map { it.publicId }

    override suspend fun getConfirmed(ledgerId: String): List<ExpenseEntity> {
        return expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }
    }

    override suspend fun getPending(ledgerId: String): List<ExpenseEntity> {
        return expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "pending" }
            .sortedWith(compareByDescending<ExpenseEntity> { it.createdAt }.thenByDescending { it.serverId })
    }

    override suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity? {
        return expenses.values.firstOrNull { it.ledgerId == ledgerId && it.serverId == serverId }
    }

    override suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity> {
        val wanted = serverIds.toSet()
        return expenses.values.filter { it.ledgerId == ledgerId && it.serverId in wanted }
    }

    override suspend fun confirmedServerIdsForLedger(ledgerId: String): List<Long> {
        return expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" && it.serverId != null }
            .mapNotNull { it.serverId }
    }

    override suspend fun localRowIdForClientRef(ledgerId: String, clientRef: String): Long? =
        expenses.values.firstOrNull { it.ledgerId == ledgerId && it.clientRef == clientRef }?.id

    override suspend fun deleteByLocalId(id: Long) {
        val removed = expenses.remove(id)
        if (removed != null) emit(removed.ledgerId)
    }

    override suspend fun insert(expense: ExpenseEntity): Long {
        insertFailure?.let { throw it }
        val id = if (expense.id == 0L) nextId++ else expense.id
        expenses[id] = expense.copy(id = id)
        emit(expense.ledgerId)
        return id
    }

    override suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long> {
        return expenses.map { insert(it) }
    }

    override suspend fun upsertConfirmedStreamOffsets(offsets: List<ExpenseOffsetStreamEntity>) {
        offsets.forEach { offset -> this.offsets[offset.ledgerId to offset.publicId] = offset }
        offsets.map { it.ledgerId }.toSet().forEach(::emitOffsets)
    }

    override suspend fun update(expense: ExpenseEntity) {
        expenses[expense.id] = expense
        emit(expense.ledgerId)
    }

    override suspend fun updateAll(expenses: List<ExpenseEntity>) {
        expenses.forEach { update(it) }
    }

    override suspend fun clear() {
        events += "clear"
        val touched = expenses.values.map { it.ledgerId }.toSet()
        expenses.clear()
        touched.forEach { emit(it) }
    }

    override suspend fun clearForLedger(ledgerId: String) {
        events += "clearForLedger:$ledgerId"
        expenses.values
            .filter { it.ledgerId == ledgerId }
            .map { it.id }
            .forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    override suspend fun deleteConfirmedForLedger(ledgerId: String) {
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .map { it.id }
            .forEach { expenses.remove(it) }
        emit(ledgerId)
    }


    override suspend fun deleteConfirmedByServerIds(ledgerId: String, serverIds: List<Long>) {
        val remove = serverIds.toSet()
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" && it.serverId in remove }
            .map { it.id }
            .forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    override suspend fun clearConfirmedStreamOffsets() {
        val touched = offsets.values.map { it.ledgerId }.toSet()
        offsets.clear()
        touched.forEach(::emitOffsets)
    }

    override suspend fun clearConfirmedStreamOffsetsForLedger(ledgerId: String) {
        offsets.keys.filter { it.first == ledgerId }.forEach(offsets::remove)
        emitOffsets(ledgerId)
    }

    override suspend fun deleteConfirmedStreamOffsetsByPublicIds(
        ledgerId: String,
        publicIds: List<String>,
    ) {
        publicIds.forEach { publicId -> offsets.remove(ledgerId to publicId) }
        emitOffsets(ledgerId)
    }

    override suspend fun deleteConfirmedStreamOffsetsForRoot(ledgerId: String, rootServerId: Long) {
        offsets.entries
            .filter { (_, offset) -> offset.ledgerId == ledgerId && offset.rootServerId == rootServerId }
            .map { it.key }
            .forEach(offsets::remove)
        emitOffsets(ledgerId)
    }

    override suspend fun applyConfirmedSyncForLedger(
        ledgerId: String,
        expenses: List<ExpenseEntity>,
        replaceCache: Boolean,
        pruneScope: Set<Long>?,
    ) {
        beforeApplyConfirmedSync?.invoke()
        if (replaceCache) {
            clearForLedger(ledgerId)
        }
        expenses.forEach { upsertByServerIdForLedger(ledgerId, it) }
        if (pruneScope != null) {
            val remoteServerIds = expenses.map { it.serverId }.toSet()
            val staleServerIds = confirmedServerIdsForLedger(ledgerId)
                .filter { it !in remoteServerIds && it in pruneScope }
            if (staleServerIds.isNotEmpty()) {
                deleteConfirmedByServerIds(ledgerId, staleServerIds)
            }
        }
        onAfterApplyConfirmedSync?.invoke()
    }

    override suspend fun applyConfirmedStreamSyncForLedger(
        ledgerId: String,
        roots: List<ExpenseEntity>,
        offsets: List<ExpenseOffsetStreamEntity>,
        replaceCache: Boolean,
        pruneScope: ConfirmedStreamPruneScope,
    ): Set<Long> {
        beforeApplyConfirmedSync?.invoke()
        val accepted = super<ExpenseDao>.applyConfirmedStreamSyncForLedger(ledgerId, roots, offsets, replaceCache, pruneScope)
        onAfterApplyConfirmedSync?.invoke()
        return accepted
    }

    private fun flowFor(ledgerId: String): MutableStateFlow<List<ExpenseEntity>> =
        flows.getOrPut(ledgerId) { MutableStateFlow(snapshot(ledgerId)) }

    private fun snapshot(ledgerId: String): List<ExpenseEntity> =
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }

    private fun offsetFlowFor(ledgerId: String): MutableStateFlow<List<ExpenseOffsetStreamEntity>> =
        offsetFlows.getOrPut(ledgerId) { MutableStateFlow(offsetSnapshot(ledgerId)) }

    private fun offsetSnapshot(ledgerId: String): List<ExpenseOffsetStreamEntity> =
        offsets.values.filter { it.ledgerId == ledgerId }.sortedByDescending { it.streamDate }

    private fun emit(ledgerId: String) {
        flowFor(ledgerId).value = snapshot(ledgerId)
    }

    private fun emitOffsets(ledgerId: String) {
        offsetFlowFor(ledgerId).value = offsetSnapshot(ledgerId)
    }
}

private fun hasCompleteStreamProjection(expense: ExpenseEntity): Boolean =
    expense.streamDate != null &&
        expense.streamAmountCents != null &&
        expense.lineageStatus != null &&
        expense.lineageHomeNetCents != null
