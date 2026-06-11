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
    fun upsertDoesNotMoveSameServerIdAcrossLedgers() = runTest {
        val dao = FakeExpenseDao()

        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 42, merchant = "owner row"))
        dao.upsertByServerIdForLedger("L_family", entity("L_family", serverId = 42, merchant = "family row"))

        val owner = dao.getConfirmed("owner").single()
        val family = dao.getConfirmed("L_family").single()
        assertEquals("owner", owner.ledgerId)
        assertEquals("owner row", owner.merchant)
        assertEquals("L_family", family.ledgerId)
        assertEquals("family row", family.merchant)
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

    @Test
    fun upsertGuardKeepsNewerRowAgainstStaleSnapshot() = runTest {
        // Audit P3 #12: a slow full-list sync (stale rowVersion) must not
        // clobber the row a fresh PATCH already advanced. Same-or-newer
        // versions still apply (identical token = identical server payload).
        val dao = FakeExpenseDao()

        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 9, merchant = "patched", rowVersion = 5))
        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 9, merchant = "stale-sync", rowVersion = 3))

        val row = dao.getConfirmed("owner").single()
        assertEquals("patched", row.merchant)
        assertEquals(5L, row.rowVersion)

        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 9, merchant = "newer", rowVersion = 6))
        assertEquals("newer", dao.getConfirmed("owner").single().merchant)
    }

    @Test
    fun bulkUpsertGuardFiltersStaleRowsPerEntity() = runTest {
        val dao = FakeExpenseDao()
        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 1, merchant = "a-v4", rowVersion = 4))
        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 2, merchant = "b-v1", rowVersion = 1))

        dao.upsertAllByServerIdForLedger(
            "owner",
            listOf(
                entity("owner", serverId = 1, merchant = "a-stale", rowVersion = 2),
                entity("owner", serverId = 2, merchant = "b-v3", rowVersion = 3),
                entity("owner", serverId = 3, merchant = "c-new", rowVersion = 1),
            ),
        )

        val byServerId = dao.getConfirmed("owner").associateBy { it.serverId }
        assertEquals("a-v4", byServerId[1L]?.merchant)
        assertEquals("b-v3", byServerId[2L]?.merchant)
        assertEquals("c-new", byServerId[3L]?.merchant)
    }

    @Test
    fun confirmedSyncPruneSparesRowsCachedAfterTheSnapshot() = runTest {
        // Audit follow-up P2: the full-list response is a snapshot of the
        // server at request time. A row confirmed-and-cached while the fetch
        // was in flight is missing from that response by timing alone — the
        // prune must only delete rows that already existed pre-fetch.
        val dao = FakeExpenseDao()
        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 1, merchant = "pre-existing"))
        val preFetchSnapshot = dao.confirmedServerIdsForLedger("owner").toSet()
        // Confirmed mid-fetch: cached after the snapshot, absent from the
        // (stale) response below.
        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 2, merchant = "in-flight-confirm"))

        dao.applyConfirmedSyncForLedger(
            ledgerId = "owner",
            expenses = listOf(entity("owner", serverId = 1, merchant = "pre-existing")),
            replaceCache = false,
            pruneScope = preFetchSnapshot,
        )

        assertEquals(setOf(1L, 2L), dao.getConfirmed("owner").map { it.serverId }.toSet())
    }

    @Test
    fun confirmedSyncPruneStillRemovesServerDeletedRows() = runTest {
        val dao = FakeExpenseDao()
        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 1))
        dao.upsertByServerIdForLedger("owner", entity("owner", serverId = 9, merchant = "deleted-on-server"))
        val preFetchSnapshot = dao.confirmedServerIdsForLedger("owner").toSet()

        dao.applyConfirmedSyncForLedger(
            ledgerId = "owner",
            expenses = listOf(entity("owner", serverId = 1)),
            replaceCache = false,
            pruneScope = preFetchSnapshot,
        )

        assertEquals(listOf(1L), dao.getConfirmed("owner").map { it.serverId })
    }

    private fun entity(
        ledgerId: String,
        serverId: Long,
        status: String = "confirmed",
        amountCents: Long? = 100,
        merchant: String? = "merchant",
        rowVersion: Long = 1L,
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
            rowVersion = rowVersion,
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

    override suspend fun confirmedServerIdsForLedger(ledgerId: String): List<Long> {
        return expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .map { it.serverId }
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

    override suspend fun deleteConfirmedForLedger(ledgerId: String) {
        val ids = expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .map { it.id }
        ids.forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    override suspend fun deleteConfirmedByServerIds(ledgerId: String, serverIds: List<Long>) {
        val remove = serverIds.toSet()
        val ids = expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" && it.serverId in remove }
            .map { it.id }
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
