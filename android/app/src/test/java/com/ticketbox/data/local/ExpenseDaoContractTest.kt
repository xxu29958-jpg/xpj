package com.ticketbox.data.local

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ExpenseDaoContractTest {
    @Test
    fun upsertForLedgerUpdatesConfirmedCacheWithoutDuplicating() = runTest {
        val dao = FakeExpenseDao()

        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 7, amountCents = 1000, merchant = "first"))
        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 7, amountCents = 1888, merchant = "updated"))

        val confirmed = dao.getConfirmed("owner")
        assertEquals(1, confirmed.size)
        assertEquals(7, confirmed.single().serverId)
        assertEquals(1888, confirmed.single().amountCents)
        assertEquals("updated", confirmed.single().merchant)
    }

    @Test
    fun confirmedCacheExcludesPendingAndRejected() = runTest {
        val dao = FakeExpenseDao()

        dao.insert(entity("owner", serverId = 1, status = "pending"))
        dao.insert(entity("owner", serverId = 2, status = "confirmed"))
        dao.insert(entity("owner", serverId = 3, status = "rejected"))

        assertEquals(listOf(2L), dao.getConfirmed("owner").map { it.serverId })
        assertEquals(listOf(2L), dao.observeConfirmed("owner").first().map { it.serverId })
    }

    @Test
    fun confirmedCacheIsIsolatedAcrossLedgers() = runTest {
        val dao = FakeExpenseDao()

        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 100))
        dao.upsertByServerIdForLedger("L_family", entity("L_family", serverId = 200))

        val ownerView = dao.getConfirmed("owner")
        val familyView = dao.getConfirmed("L_family")
        assertEquals(listOf(100L), ownerView.map { it.serverId })
        assertEquals(listOf(200L), familyView.map { it.serverId })

        val observedOwner = dao.observeConfirmed("owner").first()
        val observedFamily = dao.observeConfirmed("L_family").first()
        assertEquals(listOf(100L), observedOwner.map { it.serverId })
        assertEquals(listOf(200L), observedFamily.map { it.serverId })
    }

    @Test
    fun clearForLedgerOnlyDropsTargetLedger() = runTest {
        val dao = FakeExpenseDao()
        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 1))
        dao.upsertByServerIdForLedger("L_family", entity("L_family", serverId = 2))

        dao.clearForLedger("owner")

        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertEquals(listOf(2L), dao.getConfirmed("L_family").map { it.serverId })
    }

    @Test
    fun upsertAllRejectsMixedLedgerBatch() = runTest {
        val dao = FakeExpenseDao()
        val mixed = listOf(
            entity("owner", serverId = 1),
            entity("L_family", serverId = 2),
        )
        var threw = false
        try {
            dao.upsertAllByServerIdForLedger("owner", mixed)
        } catch (error: IllegalArgumentException) {
            threw = true
        }
        assertTrue(threw, "mixed-ledger batch must throw")
    }

    @Test
    fun findByServerIdIsLedgerScoped() = runTest {
        val dao = FakeExpenseDao()
        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 42))
        dao.upsertByServerIdForLedger("L_family", entity("L_family", serverId = 43))

        assertEquals(42, dao.findByServerId("owner", 42)?.serverId)
        // Looking up 43 in the wrong ledger must miss.
        assertEquals(null, dao.findByServerId("owner", 43))
        assertEquals(listOf(43L), dao.findByServerIds("L_family", listOf(42L, 43L)).map { it.serverId })
    }

    private fun entity(
        ledgerId: String,
        serverId: Long,
        status: String = "confirmed",
        amountCents: Long? = 100,
        merchant: String? = "merchant",
    ): ExpenseEntity {
        return ExpenseEntity(
            ledgerId = ledgerId,
            serverId = serverId,
            publicId = "public-$ledgerId-$serverId",
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

/**
 * In-memory ledger-scoped fake. Mirrors the real DAO's invariants without
 * Room: queries always filter by ledgerId, and `upsertAllByServerIdForLedger`
 * rejects mixed-ledger batches.
 */
private class FakeExpenseDao : ExpenseDao {
    private val expenses = linkedMapOf<Long, ExpenseEntity>()
    private val perLedgerFlows = mutableMapOf<String, MutableStateFlow<List<ExpenseEntity>>>()
    private var nextId = 1L

    override fun observeConfirmed(ledgerId: String): Flow<List<ExpenseEntity>> {
        return flowFor(ledgerId)
    }

    override suspend fun getConfirmed(ledgerId: String): List<ExpenseEntity> {
        return expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }
    }

    override suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity? {
        return expenses.values.firstOrNull { it.ledgerId == ledgerId && it.serverId == serverId }
    }

    override suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity> {
        val wanted = serverIds.toSet()
        return expenses.values.filter { it.ledgerId == ledgerId && it.serverId in wanted }
    }

    override suspend fun findAnyByServerIds(serverIds: List<Long>): List<ExpenseEntity> {
        val wanted = serverIds.toSet()
        return expenses.values.filter { it.serverId in wanted }
    }

    override suspend fun insert(expense: ExpenseEntity): Long {
        val id = if (expense.id == 0L) nextId++ else expense.id
        expenses[id] = expense.copy(id = id)
        emit(expense.ledgerId)
        return id
    }

    override suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long> {
        return expenses.map { insert(it) }
    }

    override suspend fun update(expense: ExpenseEntity) {
        expenses[expense.id] = expense
        emit(expense.ledgerId)
    }

    override suspend fun updateAll(expenses: List<ExpenseEntity>) {
        expenses.forEach { update(it) }
    }

    override suspend fun clear() {
        val touched = expenses.values.map { it.ledgerId }.toSet()
        expenses.clear()
        touched.forEach { emit(it) }
    }

    override suspend fun clearForLedger(ledgerId: String) {
        val ids = expenses.values.filter { it.ledgerId == ledgerId }.map { it.id }
        ids.forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    private fun flowFor(ledgerId: String): MutableStateFlow<List<ExpenseEntity>> {
        return perLedgerFlows.getOrPut(ledgerId) {
            MutableStateFlow(snapshot(ledgerId))
        }
    }

    private fun snapshot(ledgerId: String): List<ExpenseEntity> =
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }

    private fun emit(ledgerId: String) {
        flowFor(ledgerId).value = snapshot(ledgerId)
    }
}
