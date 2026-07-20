package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class OutboxBindingIsolationTest {
    @Test
    fun sameDeviceRecoveryMakesItsQuarantinedIntentRunnableAgain() = runTest {
        val dao = FakePendingMutationDao()
        val original = testOutboxBinding().copy(ledgerId = "owner")
        var binding = original
        val repo = testOutboxRepository(dao = dao, bindingProvider = { binding })
        repo.enqueue(PendingMutationType.CreateExpense, "expense:local:recover", "{}", 0L)

        repo.withBindingTransition { binding = OutboxBinding.DEFAULT }
        assertEquals(1, repo.observeStatus().first().quarantinedCount)
        assertTrue(repo.dequeueNextRunnable().isEmpty())

        repo.withBindingTransition { binding = original }
        assertEquals(0, repo.observeStatus().first().quarantinedCount)
        assertEquals(1, repo.dequeueNextRunnable().size)
    }

    @Test
    fun anotherDeviceCannotSeeOrReplayThePreviousDevicesIntent() = runTest {
        val dao = FakePendingMutationDao()
        var binding = testOutboxBinding().copy(ledgerId = "owner")
        val repo = testOutboxRepository(dao = dao, bindingProvider = { binding })
        repo.enqueue(PendingMutationType.CreateExpense, "expense:local:abc", "{}", 0L)

        binding = binding.copy(owner = testOwner("50000000"))
        val status = repo.observeStatus().first()

        assertTrue(repo.dequeueNextRunnable().isEmpty())
        assertEquals(0, status.queueDepth)
        assertTrue(status.conflicts.isEmpty())
        assertTrue(status.failed.isEmpty())
        assertEquals(1, status.quarantinedCount)
    }

    @Test
    fun explicitClearRemovesOnlyQuarantinedOwners() = runTest {
        val dao = FakePendingMutationDao()
        val active = testOutboxBinding().copy(ledgerId = "owner")
        var binding = active
        val repo = testOutboxRepository(dao = dao, bindingProvider = { binding })
        val activeId = repo.enqueue(PendingMutationType.CreateExpense, "expense:local:mine", "{}", 0L)
        binding = active.copy(owner = testOwner("50000000"))
        repo.enqueue(PendingMutationType.CreateExpense, "expense:local:other", "{}", 0L)
        binding = active

        assertEquals(1, repo.clearQuarantined())
        assertEquals(setOf(activeId), dao.rows.keys)
        assertEquals(0, repo.observeStatus().first().quarantinedCount)
        assertEquals(1, repo.observeStatus().first().queueDepth)
    }

    @Test
    fun rebindAtEnqueueLinearizationPointRejectsTheOldIntent() = runTest {
        val dao = FakePendingMutationDao()
        var current = boundSession("https://one.example.com", "token-a", "session-a", "binding-a")
        var binding = current.outboxBinding
        val repo = testOutboxRepository(dao = dao, bindingProvider = { binding })
        val bound = BoundLedgerRequest(
            service = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0),
            snapshot = current,
            currentSnapshot = { current },
        )

        bound.requireStillActive()
        current = boundSession("https://two.example.com", "token-b", "session-b", "binding-b")
        binding = current.outboxBinding

        assertFailsWith<RepositoryException> {
            repo.enqueue(
                boundRequest = bound,
                intent = PendingMutationIntent(
                    type = PendingMutationType.PatchExpense,
                    targetId = "expense:1",
                    payloadJson = "{}",
                    expectedRowVersion = 1L,
                ),
            )
        }
        assertTrue(dao.rows.isEmpty())
    }

    @Test
    fun staleStatusActionCannotResolveRowFromPreviousBinding() = runTest {
        val dao = FakePendingMutationDao()
        var binding = testOutboxBinding().copy(serverUrl = "https://one.example.com", ledgerId = "ledger-a")
        val repo = testOutboxRepository(dao = dao, bindingProvider = { binding })
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        repo.markConflict(id, "state conflict")

        repo.withBindingTransition {
            binding = testOutboxBinding().copy(
                serverUrl = "https://two.example.com",
                ledgerId = "ledger-a",
                owner = testOwner("40000000"),
            )
        }

        assertEquals(false, repo.resolveConflict(id, ConflictResolution.DropMine))
        assertEquals(PendingMutationStatus.Conflict.wireValue, dao.rows.getValue(id).status)
        assertEquals("https://one.example.com", dao.rows.getValue(id).serverUrl)
    }

    private fun boundSession(
        serverUrl: String,
        token: String,
        sessionGeneration: String,
        bindingRevision: String,
    ) = BoundSessionSnapshot(
        serverUrl = serverUrl,
        ledgerId = "ledger-a",
        owner = requireNotNull(testOutboxBinding().owner),
        token = token,
        sessionGeneration = sessionGeneration,
        bindingRevision = bindingRevision,
    )

    private fun testOwner(prefix: String): OutboxOwnerIdentity = requireNotNull(
        OutboxOwnerIdentity.fromOrNull(
            serverId = "$prefix-0000-0000-0000-000000000001",
            dataGeneration = "$prefix-0000-0000-0000-000000000002",
            accountPublicId = "$prefix-0000-0000-0000-000000000003",
            devicePublicId = "$prefix-0000-0000-0000-000000000004",
        ),
    )
}
