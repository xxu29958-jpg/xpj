package com.ticketbox.data.repository

import androidx.test.core.app.ApplicationProvider
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.GoalDraft
import java.io.IOException
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Disk Room proves original admission across lost local acknowledgement and independent queue instances. */
class GoalCreationAdmissionRoomTest {
    private val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext())
    private val adapters = OutboxAdapterGraph()
    private val draft = GoalDraft("旅行", "2026-09", 1200, "交通", "JPY")
    private val key = UUID.randomUUID().toString()

    @After fun close() = fixture.close()

    @Test fun lostLocalAcknowledgementReopensTheBareOriginalAndAcceptsItOnce() = runBlocking {
        val binding = requireNotNull(fixture.reopen().goalEditRepository.currentAccess()).binding
        val row = intent(key).toEntity(outboxBinding(binding), Instant.now(fixture.clock).toString())
        // The Room transaction commits, but the caller never obtains its returned id.
        val acknowledgement = runCatching {
            fixture.pendingDao.insertOriginalCreation(row)
            throw IOException("Synthetic local acknowledgement lost after Room commit")
        }
        assertTrue(acknowledgement.isFailure)
        val original = fixture.stored().single()
        val repository = fixture.reopen().goalEditRepository
        val reopened = requireNotNull(repository.originalCreation(binding, key).getOrThrow())
        assertEquals(original["id"]?.toLong(), reopened.row.id)
        assertEquals("JPY", reopened.request?.homeCurrencyCode)
        assertEquals(1200L, reopened.request?.targetAmountCents)
        assertEquals(reopened.row.id, repository.create(binding, draft, key).getOrThrow())
        assertEquals(listOf(original), fixture.stored())
        assertEquals(1, fixture.schedules)
    }

    @Test fun concurrentQueueInstancesAcceptOneOriginalCreation() = runBlocking {
        val repository = fixture.reopen().goalEditRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        val second = OutboxRepository(fixture.pendingDao, fixture.clock, onRowsDeleted = {},
            bindingProvider = { outboxBinding(binding) })
        val snapshot = BoundSessionSnapshot(binding.serverUrl, binding.ledgerId,
            requireNotNull(OutboxOwnerIdentity.parseOrNull(binding.ownerKey)), "synthetic-session",
            binding.sessionGeneration, binding.bindingRevision)
        val bound = BoundLedgerRequest(fixture.network.service, snapshot) { snapshot }
        val start = CompletableDeferred<Unit>()
        val admissions = listOf(fixture.outbox, second).map { queue ->
            async(Dispatchers.IO) {
                start.await()
                queue.enqueueOriginalCreation(bound, intent(key))
            }
        }
        start.complete(Unit)
        val ids = admissions.awaitAll()
        assertEquals(ids.first(), ids.last())
        val original = requireNotNull(repository.originalCreation(binding, key).getOrThrow())
        assertEquals(ids.first(), original.row.id)
        assertEquals("旅行", original.request?.name)
        assertEquals(1200L, original.request?.targetAmountCents)
        assertEquals(1, fixture.stored().size)
    }

    @Test fun anotherTaskKeyPreservesAnIdenticalLegacyOriginalAsAnIndependentCreation() = runBlocking {
        val repository = fixture.reopen().goalEditRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        val legacy = intent(key).toEntity(outboxBinding(binding), Instant.now(fixture.clock).toString())
        fixture.pendingDao.insert(legacy)
        val original = fixture.stored().single()
        val nextKey = UUID.randomUUID().toString()
        assertNull(repository.originalCreation(binding, nextKey).getOrThrow())
        val nextId = repository.create(binding, draft, nextKey).getOrThrow()
        val next = requireNotNull(repository.originalCreation(binding, nextKey).getOrThrow())
        assertNotEquals(original["id"]?.toLong(), nextId)
        assertEquals(nextId, next.row.id)
        assertEquals(original["payload"], next.row.payloadJson)
        assertEquals(original, fixture.stored().first())
        assertEquals(2, fixture.stored().size)
    }

    @Test fun sameKeyCannotReplaceOriginalBodyTargetOrExpectedVersion() = runBlocking {
        val repository = fixture.reopen().goalEditRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        repository.create(binding, draft, key).getOrThrow()
        val original = fixture.stored().single()
        assertTrue(repository.create(binding, draft.copy(targetAmountCents = 1300), key).isFailure)
        val row = intent(key).toEntity(outboxBinding(binding), Instant.now(fixture.clock).toString())
        for (changed in listOf(row.copy(targetId = "goal_create:another"), row.copy(expectedRowVersion = 1))) {
            assertOriginalRefused(changed)
        }
        assertEquals(listOf(original), fixture.stored())
        assertEquals(1200L, repository.originalCreation(binding, key).getOrThrow()?.request?.targetAmountCents)
    }

    @Test fun keyedLookupRetainsUnknownAndAbandonedOriginalsWithoutReopeningSubmission() = runBlocking {
        val repository = fixture.reopen().goalEditRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        for ((wireStatus, status) in listOf("future_goal_state" to PendingMutationStatus.Unknown,
            "abandoned" to PendingMutationStatus.Abandoned)) {
            val originalKey = UUID.randomUUID().toString()
            val row = intent(originalKey).toEntity(outboxBinding(binding), Instant.now(fixture.clock).toString())
                .copy(status = wireStatus)
            val id = fixture.pendingDao.insert(row)
            val original = requireNotNull(repository.originalCreation(binding, originalKey).getOrThrow())
            assertEquals(id, original.row.id)
            assertEquals(status, original.row.status)
            assertEquals(1200L, original.request?.targetAmountCents)
            assertEquals(id, repository.create(binding, draft, originalKey).getOrThrow())
        }
        assertEquals(2, fixture.stored().size)
        assertTrue(repository.observeCreations(binding).first().isEmpty())
        assertEquals(listOf("future_goal_state", "abandoned"), fixture.stored().map { it["status"] })
    }

    private suspend fun assertOriginalRefused(changed: PendingMutationEntity) {
        assertTrue(runCatching { fixture.pendingDao.insertOriginalCreation(changed) }.isFailure)
    }

    private fun intent(creationKey: String) = PendingMutationIntent(PendingMutationType.CreateGoal,
        "goal_create:$creationKey", adapters.goalCreateAdapter.toJson(draft.toRequest()), 0, creationKey)

    private fun outboxBinding(binding: LogicalSessionBinding) = OutboxBinding(binding.serverUrl, binding.ledgerId,
        requireNotNull(OutboxOwnerIdentity.parseOrNull(binding.ownerKey)))
}
