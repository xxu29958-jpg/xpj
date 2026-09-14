package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto
import com.ticketbox.data.remote.dto.ConfirmedStreamEntryKindDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.ConfirmedOffsetStreamDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseOffsetDraft
import com.ticketbox.domain.model.StreamOffsetKind
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
    fun anAcceptedLocalPatchBlocksPromotedFactCommandsUntilTheCompleteReadIsAdopted() = runTest {
        for (offsetSubmission in listOf(false, true)) {
            val fixture = CorrectionRefreshFixture()
            fixture.read = { fixture.expense(it, 12L) }
            val fact = fixture.repository.fetchExpense(42).getOrThrow()
            val binding = assertNotNull(fixture.repository.observeCorrections().first().access).binding
            val request = ExpenseUpdateRequest(merchant = "Original pending edit", category = null, note = null,
                expenseTime = null, tags = null, valueScore = null, regretScore = null)
            val payload = com.ticketbox.OutboxAdapterGraph().patchExpenseAdapter.toJson(request)
            val id = fixture.outbox.enqueue(PendingMutationType.PatchExpense, "expense:local:original-create",
                payload, 10, "original-local-patch-key")
            // The delayed accepted PATCH predates the newer confirmed root; its projection could not be published.
            fixture.outbox.markDone(id, cacheRefreshVersion = 11, receiptJson = """{"expenseId":42}""")
            val original = fixture.queue.rows.getValue(id)
            val submit = suspend {
                if (offsetSubmission) fixture.repository.createExpenseOffsetAllowingOffline(binding, fact,
                    ExpenseOffsetDraft(StreamOffsetKind.Refund, 100, "2026-09-06", "Reviewed refund"))
                else fixture.repository.submitCorrection(binding, fact,
                    ExpenseCorrectionDraft("Reviewed correction", merchant = "Reviewed merchant"))
            }

            assertTrue(submit().isFailure, "Numeric admission cannot bypass its local-target accepted PATCH; offset=$offsetSubmission")
            assertEquals(listOf(original), fixture.queue.rows.values.toList())
            fixture.streamVersions[42] = 12
            fixture.repository.fetchExpense(42).getOrThrow()
            assertEquals(original.copy(lastError = null), fixture.queue.rows[id], "Root GET must also adopt the full confirmed stream")
            // Each recovered entry is independent: a queued correction correctly blocks a subsequent offset.
            submit().getOrThrow()
        }
    }
    @Test
    fun acceptedExpenseRefreshRequirementsRemainVisibleAcrossAllCommandTypes() = runTest {
        val clock = Clock.fixed(Instant.parse("2026-05-04T00:00:00Z"), ZoneOffset.UTC)
        val types = listOf(
            PendingMutationType.PatchExpense,
            PendingMutationType.ConfirmExpense,
            PendingMutationType.RejectExpense,
            PendingMutationType.MarkNotDuplicate,
            PendingMutationType.RetryOcr,
            PendingMutationType.RecognizeText,
            PendingMutationType.CreateExpenseOffset,
            PendingMutationType.VoidExpenseOffset,
        )
        for (type in types) {
            val dao = FakePendingMutationDao()
            val repo = testOutboxRepository(dao = dao, clock = clock)
            val id = repo.enqueue(type, "expense:42", "{}", 7L, idempotencyKey = "original-${type.wireValue}")
            repo.markDone(id)
            assertEquals(false, repo.observeStatus().first().needsUserAction, "$type without a refresh requirement")
            val accepted = dao.rows.getValue(id).copy(lastError = "correction_refresh_required:11")
            dao.rows[id] = accepted

            val status = repo.observeStatus().first()

            assertEquals(0, status.queueDepth, "$type is already delivered")
            assertTrue(status.conflicts.isEmpty() && status.failed.isEmpty(), "$type is not a rejected command")
            assertEquals(accepted, dao.rows[id], "Observation must preserve the original accepted $type")
            assertTrue(status.needsUserAction, "$type must expose its outstanding cache refresh")
        }
    }

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
    fun aPendingReadRejectedByNewerCacheCannotClearTheAcceptedReceipt() = runTest {
        val fixture = CorrectionRefreshFixture()
        val request = ExpenseUpdateRequest(merchant = "Reviewed merchant", category = null, note = null,
            expenseTime = null, tags = null, valueScore = null, regretScore = null)
        val payload = com.ticketbox.OutboxAdapterGraph().patchExpenseAdapter.toJson(request)
        val id = fixture.outbox.enqueue(PendingMutationType.PatchExpense, "expense:42", payload,
            10L, "original-pending-patch-key")
        fixture.outbox.markDone(id, cacheRefreshVersion = 11L)
        val original = fixture.queue.rows.getValue(id)
        fixture.cache.upsertByServerIdForLedger("owner", fixture.expense(42L, 12L)
            .copy(status = "pending", confirmedAt = null).toEntity("owner"))
        fixture.read = { fixture.expense(it, 11L).copy(status = "pending", confirmedAt = null) }

        fixture.repository.fetchExpense(42L).getOrThrow()

        val retained = fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow()
        assertEquals(12L, retained.rowVersion)
        assertEquals("pending", retained.status)
        assertEquals(original, fixture.queue.rows[original.id], "A rejected pending DTO cannot acknowledge its receipt")
        fixture.read = { fixture.expense(it, 13L).copy(status = "pending", confirmedAt = null) }
        fixture.repository.fetchExpense(42L).getOrThrow()
        assertEquals(13L, fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow().rowVersion)
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
    fun aRootOnlyMonthKeepsTheOffsetReceiptUntilTheFullStreamIsAdopted() = runTest {
        val fixture = CorrectionRefreshFixture()
        fixture.streamVersions[42L] = 7L
        val root = fixture.repository.fetchExpense(42L).getOrThrow()
        val access = assertNotNull(fixture.repository.observeCorrections().first().access)
        fixture.repository.createExpenseOffsetAllowingOffline(access.binding, root,
            ExpenseOffsetDraft(StreamOffsetKind.Refund, 100L, "2026-10-03", "Original refund")).getOrThrow()
        val id = fixture.queue.rows.values.single().id
        assertEquals(PendingMutationType.CreateExpenseOffset.wireValue, fixture.queue.rows.getValue(id).type)
        fixture.outbox.markDone(id, cacheRefreshVersion = 11L)
        val original = fixture.queue.rows.getValue(id)
        fixture.streamVersions[42L] = 11L
        fixture.streamItems = { items -> items.map { it.copy(lineageStatus = ExpenseLineageStatusDto.PartiallyRefunded,
            lineageHomeNetCents = requireNotNull(it.root.amountCents) - 100) } }

        fixture.repository.syncConfirmed(month = "2026-09").getOrThrow()

        assertEquals(11L, fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow().rowVersion)
        assertTrue(fixture.cache.getConfirmedStreamOffsets("owner").isEmpty())
        assertEquals(original, fixture.queue.rows[original.id], "A root month omits the accepted refund in another month")
        val rootProjection = fixture.streamItems
        fixture.streamItems = { rawItems ->
            val items = rootProjection(rawItems)
            items + items.map { it.copy(entryKind = ConfirmedStreamEntryKindDto.Offset,
            streamDate = "2026-10-03", streamAmountCents = -100,
            offset = ConfirmedOffsetStreamDto("refund", ExpenseOffsetKindDto.Refund, 100, 100, "CNY", "CNY", "餐饮"),
            lineageStatus = ExpenseLineageStatusDto.PartiallyRefunded,
            lineageHomeNetCents = requireNotNull(it.root.amountCents) - 100) } }
        fixture.repository.syncConfirmed().getOrThrow()
        assertEquals("refund", fixture.cache.getConfirmedStreamOffsets("owner").single().publicId)
        assertEquals(original.copy(lastError = null), fixture.queue.rows[original.id])
        assertTrue(fixture.outbox.dequeueNextRunnable().isEmpty())
    }

    @Test
    fun completedRowCleanupWaitsForCanonicalRecoveryWithoutChangingTheOriginal() = runTest {
        val fixture = CorrectionRefreshFixture()
        val original = fixture.seed(42L)
        val future = OutboxRepository(fixture.queue,
            Clock.fixed(Instant.parse("2026-09-20T00:00:00Z"), ZoneOffset.UTC),
            bindingProvider = { fixture.binding.sessionStore.currentSession().toOutboxBinding() }, onRowsDeleted = {})

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
        override suspend fun clearExpenseRefresh(id: Long, expectedError: String): Int {
            if (failAcknowledgment()) throw IOException("Synthetic local acknowledgment failure")
            return queue.clearExpenseRefresh(id, expectedError)
        }
    }
    val outbox = OutboxRepository(dao,
        Clock.fixed(Instant.parse("2026-09-06T00:00:00Z"), ZoneOffset.UTC),
        bindingProvider = { binding.sessionStore.currentSession().toOutboxBinding() }, onRowsDeleted = {})
    val repository = ExpenseRepository(cache, binding, deviceNameProvider = { "Synthetic Android" },
        offlineMutations = testExpenseOfflineMutationWiring(outbox).copy(
            offsetCreateAdapter = com.ticketbox.OutboxAdapterGraph().offsetCreateAdapter))

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
