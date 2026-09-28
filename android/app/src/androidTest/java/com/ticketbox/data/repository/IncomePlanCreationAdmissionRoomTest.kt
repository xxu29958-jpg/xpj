package com.ticketbox.data.repository

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomeSourceType
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class IncomePlanCreationAdmissionRoomTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val fixture = IncomePlanConnectedFixture(context)
    private val draft = IncomePlanDraft("2026-09", "JPY", "旅行补贴", IncomeSourceType.OTHER,
        IncomeFrequency.ONE_TIME, "2026-09", 1200, 10)
    private val key = "room-original-income-creation"

    @After fun close() { fixture.close() }

    @Test fun lostLocalAcceptanceReopensOneOriginalAndRetainedDoneCannotAllocateAnother() = runBlocking {
        val repository = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(repository.observeActiveLedgerAccess().first()).binding
        // Room accepted the command, but its caller never receives the successful local callback.
        val lostCallback = runCatching {
            repository.create(binding, draft, key).getOrThrow()
            throw IOException("Synthetic lost local acceptance callback")
        }
        assertTrue(lostCallback.isFailure)
        val stored = fixture.stored().single()
        val id = requireNotNull(stored["id"]).toLong()
        assertEquals(0, fixture.network.creationCalls.size)
        fixture.advanceToOctober()
        fixture.network.failReads = true
        val reopened = fixture.reopen().incomePlanRepository
        val pending = requireNotNull(reopened.originalCreation(binding, key).getOrThrow())
        assertEquals(id, pending.row.id)
        assertEquals("JPY", pending.intent?.homeCurrencyCode)
        assertEquals("2026-09", pending.intent?.request?.intentMonth)
        assertEquals(id, reopened.create(binding, draft, key).getOrThrow())
        assertEquals(1, fixture.stored().size)
        assertEquals(1, fixture.drain(maxAttempts = 1).failures)
        assertEquals(PendingMutationStatus.Failed, reopened.originalCreation(binding, key).getOrThrow()?.row?.status)
        assertEquals(id, reopened.create(binding, draft, key).getOrThrow())
        reopened.recoverSubmission(binding, requireNotNull(reopened.originalCreation(binding, key).getOrThrow()), false).getOrThrow()
        fixture.network.loseResponse = false
        assertEquals(1, fixture.drain().done)
        val completedRepository = fixture.reopen().incomePlanRepository
        assertTrue(requireNotNull(completedRepository.originalCreation(binding, key).getOrThrow()).isConfirmed)
        assertEquals(id, completedRepository.create(binding, draft, key).getOrThrow())
        assertEquals(1, fixture.stored().size)
        assertEquals(stored["payload"], fixture.stored().single()["payload"])
        assertEquals(listOf(key, key), fixture.network.creationCalls.map { it.second })
        assertEquals(fixture.network.creationCalls.first(), fixture.network.creationCalls.last())
        assertEquals(1, fixture.network.creationReceipts.size)
    }

    @Test fun changingSameKeyRefusesWhileIndependentKeyCanSubmitTheSameFinancialIntent() = runBlocking {
        val repository = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(repository.observeActiveLedgerAccess().first()).binding
        val id = repository.create(binding, draft, key).getOrThrow()
        val original = fixture.stored().single()
        assertTrue(repository.create(binding, draft.copy(amountCents = 2400), key).isFailure)
        assertTrue(repository.create(binding.copy(bindingRevision = "foreign-binding"), draft, key).isFailure)
        assertTrue(repository.originalCreation(binding.copy(sessionGeneration = "foreign-session"), key).isFailure)
        assertTrue(repository.originalCreation(binding.copy(ownerKey = "foreign-owner"), key).isFailure)
        assertEquals(original, fixture.stored().single())
        val independent = repository.create(binding, draft, "room-independent-income-creation").getOrThrow()
        assertNotEquals(id, independent)
        assertEquals(2, fixture.stored().size)
        assertEquals(original["payload"], fixture.stored().last()["payload"])
        assertEquals(0, fixture.network.creationCalls.size)
    }

    @Test fun separateOutboxInstancesShareAtomicRoomAcceptance() = runBlocking {
        val repository = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(repository.observeActiveLedgerAccess().first()).binding
        repository.create(binding, draft, "room-seed-income-creation").getOrThrow()
        val intent = PendingMutationIntent(PendingMutationType.CreateIncomePlan, "income_plan_create:$key",
            requireNotNull(fixture.stored().single()["payload"]), 0, key)
        val snapshot = BoundSessionSnapshot(binding.serverUrl, binding.ledgerId,
            requireNotNull(OutboxOwnerIdentity.parseOrNull(binding.ownerKey)), "synthetic-session",
            binding.sessionGeneration, binding.bindingRevision)
        val bound = BoundLedgerRequest(fixture.network.service, snapshot) { snapshot }
        val anotherDatabase = Room.databaseBuilder(context, AppDatabase::class.java, "income-plan-continuity.db").build()
        try {
            val anotherOutbox = OutboxRepository(anotherDatabase.pendingMutationDao(),
                bindingProvider = { snapshot.outboxBinding }, onRowsDeleted = {})
            val start = CompletableDeferred<Unit>()
            val acceptances = listOf(fixture.outbox, anotherOutbox).map { outbox -> async(Dispatchers.IO) {
                start.await()
                outbox.enqueueIncomeCreation(bound, intent)
            } }
            start.complete(Unit)
            val ids = acceptances.awaitAll()
            assertEquals(ids.first(), ids.last())
            assertEquals(2, fixture.stored().size)
            assertEquals(1, fixture.stored().count { it["idempotencyKey"] == key })
            val changedOcc = runCatching { anotherOutbox.enqueueIncomeCreation(bound, intent.copy(expectedRowVersion = 1)) }
            assertTrue(changedOcc.isFailure)
            assertEquals(2, fixture.stored().size)
        } finally {
            anotherDatabase.close()
        }
    }
}
