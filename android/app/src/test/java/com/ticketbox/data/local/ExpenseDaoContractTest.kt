package com.ticketbox.data.local

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseDaoContractTest {
    @Test
    fun upsertByServerIdUpdatesConfirmedCacheWithoutDuplicating() = runTest {
        val dao = FakeExpenseDao()

        dao.upsertByServerId(entity(serverId = 7, amountCents = 1000, merchant = "first"))
        dao.upsertByServerId(entity(serverId = 7, amountCents = 1888, merchant = "updated"))

        val confirmed = dao.getConfirmed()
        assertEquals(1, confirmed.size)
        assertEquals(7, confirmed.single().serverId)
        assertEquals(1888, confirmed.single().amountCents)
        assertEquals("updated", confirmed.single().merchant)
    }

    @Test
    fun confirmedCacheExcludesPendingAndRejected() = runTest {
        val dao = FakeExpenseDao()

        dao.insert(entity(serverId = 1, status = "pending"))
        dao.insert(entity(serverId = 2, status = "confirmed"))
        dao.insert(entity(serverId = 3, status = "rejected"))

        assertEquals(listOf(2L), dao.getConfirmed().map { it.serverId })
        assertEquals(listOf(2L), dao.observeConfirmed().first().map { it.serverId })
    }

    private fun entity(
        serverId: Long,
        status: String = "confirmed",
        amountCents: Long? = 100,
        merchant: String? = "merchant",
    ): ExpenseEntity {
        return ExpenseEntity(
            serverId = serverId,
            publicId = "public-$serverId",
            amountCents = amountCents,
            merchant = merchant,
            category = "餐饮",
            note = null,
            source = "iPhone截图",
            thumbnailPath = null,
            imageHash = null,
            rawText = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = status,
            expenseTime = "2026-05-04T08:23:25Z",
            createdAt = "2026-05-04T08:00:00Z",
            confirmedAt = if (status == "confirmed") "2026-05-04T08:30:00Z" else null,
            updatedAt = "2026-05-04T08:30:00Z",
        )
    }
}

private class FakeExpenseDao : ExpenseDao {
    private val expenses = linkedMapOf<Long, ExpenseEntity>()
    private val confirmedFlow = MutableStateFlow<List<ExpenseEntity>>(emptyList())
    private var nextId = 1L

    override fun observeConfirmed(): Flow<List<ExpenseEntity>> = confirmedFlow

    override suspend fun getConfirmed(): List<ExpenseEntity> {
        return expenses.values
            .filter { it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }
    }

    override suspend fun findByServerId(serverId: Long): ExpenseEntity? {
        return expenses.values.firstOrNull { it.serverId == serverId }
    }

    override suspend fun findByServerIds(serverIds: List<Long>): List<ExpenseEntity> {
        val wanted = serverIds.toSet()
        return expenses.values.filter { it.serverId in wanted }
    }

    override suspend fun insert(expense: ExpenseEntity): Long {
        val id = if (expense.id == 0L) nextId++ else expense.id
        expenses[id] = expense.copy(id = id)
        emitConfirmed()
        return id
    }

    override suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long> {
        return expenses.map { insert(it) }
    }

    override suspend fun update(expense: ExpenseEntity) {
        expenses[expense.id] = expense
        emitConfirmed()
    }

    override suspend fun updateAll(expenses: List<ExpenseEntity>) {
        expenses.forEach { update(it) }
    }

    override suspend fun clear() {
        expenses.clear()
        emitConfirmed()
    }

    private suspend fun emitConfirmed() {
        confirmedFlow.emit(getConfirmed())
    }
}
