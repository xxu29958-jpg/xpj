package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseCorrectionConcurrentAcceptanceTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test
    fun concurrentSavesCannotBothAcceptTheSameFrozenRoot() = runTest {
        val queue = FakePendingMutationDao()
        val firstRead = CompletableDeferred<Unit>()
        val releaseRead = CompletableDeferred<Unit>()
        var gateNextRead = true
        val dao = object : PendingMutationDao by queue {
            override suspend fun activeForTarget(ownerKey: String, ledgerId: String, targetId: String,
                activeStatuses: Collection<String>): List<PendingMutationEntity> {
                val rows = queue.activeForTarget(ownerKey, ledgerId, targetId, activeStatuses)
                if (gateNextRead) {
                    gateNextRead = false
                    firstRead.complete(Unit)
                    releaseRead.await()
                }
                return rows
            }
        }
        var wakeups = 0
        val outbox = testOutboxRepository(dao, onEnqueued = { wakeups++ })
        val repository = ExpenseRepository(FakeExpenseDao(),
            testServerSessionBinding(TestApiServiceFactory(FakeApiService(mutableListOf(), 0)), seededSettingsStore(), seededTokenStore()),
            offlineMutations = testExpenseOfflineMutationWiring(outbox))
        val binding = requireNotNull(repository.observeCorrections().first().access).binding
        val root = successExpenseDto().copy(status = "confirmed", rowVersion = 7).toDomain()
        val first = async { repository.submitCorrection(binding, root, ExpenseCorrectionDraft("First form", note = "First")) }
        firstRead.await()
        val second = async { repository.submitCorrection(binding, root, ExpenseCorrectionDraft("Second form", note = "Second")) }
        runCurrent()
        releaseRead.complete(Unit)
        val results = listOf(first.await(), second.await())

        assertEquals(1, results.count { it.isSuccess }, "Only one form may report durable acceptance of the frozen root")
        assertEquals(1, results.count { it.isFailure })
        val accepted = repository.observeCorrections().first().corrections.single()
        assertEquals(7L, accepted.row.expectedRowVersion)
        assertEquals(1, wakeups)
        assertEquals(1, queue.rows.size)
        assertTrue(accepted.row.idempotencyKey?.isNotBlank() == true)
        val request = requireNotNull(accepted.intent).request
        assertEquals("First form", request.reason)
        assertEquals("First", request.note)
    }
}
