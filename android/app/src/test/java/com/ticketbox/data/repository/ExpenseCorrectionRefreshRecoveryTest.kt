package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto
import com.ticketbox.data.remote.dto.ConfirmedStreamEntryKindDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.ConfirmedOffsetStreamDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

internal class ExpenseCorrectionRefreshRecoveryTest {
    @Test
    fun aReadRejectedByTheCacheCannotAcknowledgeItsIncomingStreamVersion() = runTest {
        val fixture = CorrectionRefreshFixture()
        val original = fixture.seed(42L)
        fixture.read = { fixture.expense(it, 11L) }
        fixture.streamVersions[42L] = 11L
        fixture.cache.beforeApplyConfirmedSync = {
            fixture.cache.upsertByServerIdForLedger("owner", fixture.expense(42L, 12L).toEntity("owner"))
        }

        fixture.repository.fetchExpense(42L).getOrThrow()

        assertEquals(12L, fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow().rowVersion)
        assertEquals(original, fixture.queue.rows[original.id], "An incoming response is not proof of cache acceptance")
        fixture.cache.beforeApplyConfirmedSync = null
        fixture.streamVersions[42L] = 12L
        fixture.repository.syncConfirmed().getOrThrow()
        assertEquals(original.copy(lastError = null), fixture.queue.rows[original.id])
        assertTrue(fixture.outbox.dequeueNextRunnable().isEmpty())
    }

    @Test
    fun failedLocalAcknowledgmentKeepsRecoveryWithoutFailingAnAdoptedRead() = runTest {
        var failAcknowledgment = false
        val fixture = CorrectionRefreshFixture { failAcknowledgment }
        val original = fixture.seed(42L)
        fixture.read = { fixture.expense(it, 11L) }
        fixture.streamVersions[42L] = 11L
        failAcknowledgment = true

        assertEquals(11L, fixture.repository.fetchExpense(42L).getOrThrow().rowVersion)
        assertEquals(11L, fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow().rowVersion)
        assertEquals(original, fixture.queue.rows[original.id])
        failAcknowledgment = false
        fixture.repository.fetchExpense(42L).getOrThrow()
        assertEquals(original.copy(lastError = null), fixture.queue.rows[original.id])
    }

    @Test
    fun onlyAnAdoptedReceiptVersionClearsItsOwnRefreshRequirement() = runTest {
        val fixture = CorrectionRefreshFixture()
        val original = fixture.seed(42L)
        val other = fixture.seed(43L)
        fixture.read = { fixture.expense(it, 8L) }
        fixture.streamVersions[42L] = 8L

        val stale = fixture.repository.fetchExpense(42L).getOrThrow()
        assertEquals(8L, stale.rowVersion)
        assertEquals(original, fixture.queue.rows[original.id])
        val binding = assertNotNull(fixture.repository.observeCorrections().first().access).binding
        assertTrue(fixture.repository.submitCorrection(binding, stale,
            ExpenseCorrectionDraft("Another correction", merchant = "Must wait")).isFailure)
        assertEquals(2, fixture.queue.rows.size)

        fixture.read = { fixture.expense(it, 11L) }
        fixture.streamVersions[42L] = 11L
        assertEquals(11L, fixture.repository.fetchExpense(42L).getOrThrow().rowVersion)
        assertEquals(original.copy(lastError = null), fixture.queue.rows[original.id])
        assertEquals(other, fixture.queue.rows[other.id])
        assertTrue(fixture.outbox.dequeueNextRunnable().isEmpty())
    }

    @Test
    fun aReadFromAnObsoleteBindingCannotClearTheOriginalReceiptBarrier() = runTest {
        val fixture = CorrectionRefreshFixture()
        val original = fixture.seed(42L)
        val started = CompletableDeferred<Unit>()
        val response = CompletableDeferred<ExpenseDto>()
        fixture.read = { started.complete(Unit); response.await() }
        val reading = async(start = CoroutineStart.UNDISPATCHED) { fixture.repository.fetchExpense(42L) }
        started.await()
        fixture.session.switchLedgerForFixture("other-ledger", "Another family", role = "member")
        response.complete(fixture.expense(42L, 11L))

        assertTrue(reading.await().isFailure)
        assertEquals(original, fixture.queue.rows[original.id])
        assertEquals(7L, fixture.cache.getConfirmed("owner").single().rowVersion)
        assertTrue(fixture.cache.getConfirmed("other-ledger").isEmpty())
    }

    @Test
    fun anOffsetOnlyMonthCannotAcknowledgeTheRootsMissingStreamProjection() = runTest {
        val fixture = CorrectionRefreshFixture()
        val original = fixture.seed(42L)
        fixture.streamVersions[42L] = 11L
        fixture.streamItems = { items -> items.map { it.copy(entryKind = ConfirmedStreamEntryKindDto.Offset,
            streamAmountCents = -100, offset = ConfirmedOffsetStreamDto("refund", ExpenseOffsetKindDto.Refund,
                100, 100, "CNY", "CNY", "餐饮"), lineageStatus = ExpenseLineageStatusDto.PartiallyRefunded,
            lineageHomeNetCents = requireNotNull(it.root.amountCents) - 100) } }

        fixture.repository.syncConfirmed(month = "2026-09").getOrThrow()
        assertEquals(11L, fixture.repository.fetchExpenseFromLocalCache(42).getOrThrow().rowVersion)
        assertEquals(original, fixture.queue.rows[original.id], "An offset's root DTO carries no root accounting date")
        fixture.streamItems = { it }
        fixture.read = { fixture.expense(it, 11L) }
        fixture.repository.fetchExpense(42L).getOrThrow()
        assertEquals(original.copy(lastError = null), fixture.queue.rows[original.id])
    }

    @Test
    fun completedRowCleanupWaitsForCanonicalRecoveryWithoutChangingTheOriginal() = runTest {
        val fixture = CorrectionRefreshFixture()
        val original = fixture.seed(42L)
        val future = OutboxRepository(fixture.queue,
            Clock.fixed(Instant.parse("2026-09-20T00:00:00Z"), ZoneOffset.UTC),
            bindingProvider = { fixture.binding.sessionStore.currentSession().toOutboxBinding() })

        assertEquals(0, future.gcCompleted())
        assertEquals(original, fixture.queue.rows[original.id])
        fixture.read = { fixture.expense(it, 11L) }
        fixture.streamVersions[42L] = 11L
        fixture.repository.fetchExpense(42L).getOrThrow()
        assertEquals(original.copy(lastError = null), fixture.queue.rows[original.id])
        assertEquals(1, future.gcCompleted())
        assertTrue(fixture.queue.rows.isEmpty())
    }
}

private class CorrectionRefreshFixture(failAcknowledgment: () -> Boolean = { false }) : ExpensePendingRepositoryOutboxTestBase() {
    val session = seededTokenStore()
    val queue = FakePendingMutationDao()
    val cache = FakeExpenseDao()
    val streamVersions = mutableMapOf<Long, Long>()
    var streamItems: (List<ConfirmedExpenseStreamItemDto>) -> List<ConfirmedExpenseStreamItemDto> = { it }
    var read: suspend (Long) -> ExpenseDto = { expense(it, 7L) }
    private val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun expense(id: Long): ExpenseDto = read(id)
        override suspend fun confirmedExpenses(query: Map<String, String>): PaginatedExpensesDto {
            val items = streamVersions.map { (id, version) ->
                val root = this@CorrectionRefreshFixture.expense(id, version)
                ConfirmedExpenseStreamItemDto(ConfirmedStreamEntryKindDto.Expense, "2026-09-06",
                    root.createdAt, id, root.amountCents ?: 0, root,
                    lineageStatus = ExpenseLineageStatusDto.Confirmed, lineageHomeNetCents = root.amountCents ?: 0)
            }
            val selected = streamItems(items)
            return PaginatedExpensesDto(selected, 1, 200, selected.size)
        }
    }
    val binding = testServerSessionBinding(TestApiServiceFactory(api), seededSettingsStore(), session)
    private val dao = object : PendingMutationDao by queue {
        override suspend fun clearCorrectionRefresh(id: Long, expectedError: String): Int {
            if (failAcknowledgment()) throw IOException("Synthetic local acknowledgment failure")
            return queue.clearCorrectionRefresh(id, expectedError)
        }
    }
    val outbox = OutboxRepository(dao,
        Clock.fixed(Instant.parse("2026-09-06T00:00:00Z"), ZoneOffset.UTC),
        bindingProvider = { binding.sessionStore.currentSession().toOutboxBinding() })
    val repository = ExpenseRepository(cache, binding, deviceNameProvider = { "Synthetic Android" },
        offlineMutations = testExpenseOfflineMutationWiring(outbox))

    fun expense(id: Long, version: Long): ExpenseDto = successExpenseDto().copy(
        id = id, publicId = "expense-$id", status = "confirmed", rowVersion = version,
        confirmedAt = "2026-09-06T00:00:00Z",
    )

    suspend fun seed(expenseId: Long): PendingMutationEntity {
        streamVersions[expenseId] = 7L
        val fact = repository.fetchExpense(expenseId).getOrThrow()
        val access = assertNotNull(repository.observeCorrections().first().access)
        val id = repository.submitCorrection(access.binding, fact,
            ExpenseCorrectionDraft("Original correction", merchant = "Reviewed merchant")).getOrThrow()
        outbox.markDone(id)
        // A persisted known-delivery receipt, independent of the decoder being verified.
        return queue.rows.getValue(id).copy(lastError = "correction_refresh_required:11")
            .also { queue.rows[id] = it }
    }
}
