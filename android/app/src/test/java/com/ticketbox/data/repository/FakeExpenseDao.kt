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
) : ExpenseDao {
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

    override suspend fun deletePendingForLedger(ledgerId: String) {
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "pending" }
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
    ) {
        beforeApplyConfirmedSync?.invoke()
        if (replaceCache) {
            clearForLedger(ledgerId)
            clearConfirmedStreamOffsetsForLedger(ledgerId)
        }
        roots.forEach { upsertByServerIdForLedger(ledgerId, it) }
        upsertConfirmedStreamOffsets(offsets)
        if (pruneScope.rootServerIds != null) {
            val remoteIds = roots.mapNotNull { it.serverId }.toSet()
            deleteConfirmedByServerIds(ledgerId, pruneScope.rootServerIds.filter { it !in remoteIds })
        }
        if (pruneScope.offsetPublicIds != null) {
            val remoteIds = offsets.map { it.publicId }.toSet()
            deleteConfirmedStreamOffsetsByPublicIds(
                ledgerId,
                pruneScope.offsetPublicIds.filter { it !in remoteIds },
            )
        }
        onAfterApplyConfirmedSync?.invoke()
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
