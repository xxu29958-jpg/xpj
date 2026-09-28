package com.ticketbox.data.repository

import androidx.test.core.app.ApplicationProvider
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtGoalLinkViewDto
import com.ticketbox.data.remote.dto.DebtRepaymentEvaluationDto
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.domain.model.GoalDraft
import java.io.IOException
import java.net.ConnectException
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Disk Room retains the frozen debt selection; remote receipts remain separate from current goal reads. */
class DebtGoalCreationAdmissionRoomTest {
    private val f = DebtCreationConnectedFixture()

    @After fun close() = f.fixture.close()

    @Test fun lostLocalAndRemoteAcknowledgementsReopenOneOriginalWithItsFirstNonmonetaryReceipt() = runBlocking {
        var repository = f.fixture.reopen().goalEditRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        val row = f.intent(f.key).toEntity(debtOutboxBinding(binding), Instant.now(f.fixture.clock).toString())
        assertTrue(runCatching {
            f.fixture.pendingDao.insertOriginalCreation(row)
            throw IOException("Synthetic local acknowledgement lost after Room commit")
        }.isFailure)
        val stored = f.fixture.stored().single()
        repository = f.fixture.reopen().goalEditRepository
        val original = requireNotNull(repository.originalCreation(binding, f.key).getOrThrow())
        assertEquals(stored["id"]?.toLong(), original.row.id)
        assertEquals(listOf("debt-b", "debt-a"), original.request?.debtPublicIds)
        assertEquals(original.row.id, repository.create(binding, f.request, f.key).getOrThrow())
        assertEquals(listOf(stored), f.fixture.stored())

        f.loseRemoteAck = true
        assertEquals(1, f.drain().failures)
        val firstReceipt = f.accepted.values.single()
        repository = f.fixture.reopen().goalEditRepository
        val failed = requireNotNull(repository.originalCreation(binding, f.key).getOrThrow())
        assertTrue(failed.canRetry)
        assertEquals(failed, repository.describeCreation(failed.row))
        f.laterRemaining = 800
        f.loseRemoteAck = false
        repository.recoverCreation(binding, failed, drop = false).getOrThrow()
        assertEquals(1, f.drain().done)
        val done = requireNotNull(repository.originalCreation(binding, f.key).getOrThrow())
        assertEquals(firstReceipt.toDomain(), done.confirmed)
        assertTrue(done.isDone)
        assertEquals(1, f.accepted.size)
        assertEquals(listOf(f.request to f.key, f.request to f.key), f.calls)
        assertEquals(original.row.id, repository.create(binding, f.request, f.key).getOrThrow())
        val delivered = f.fixture.stored().single()
        for (field in listOf("payload", "targetId", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "serverUrl")) {
            assertEquals(field, stored[field], delivered[field])
        }
        assertNull(done.confirmed?.homeCurrencyCode)
        assertNull(done.request?.targetAmountCents)
    }

    @Test fun concurrentQueueInstancesRetainOneDebtOriginalAndAnotherTaskRemainsIndependent() = runBlocking {
        val repository = f.fixture.reopen().goalEditRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        val second = OutboxRepository(f.fixture.pendingDao, f.fixture.clock, onRowsDeleted = {},
            bindingProvider = { debtOutboxBinding(binding) })
        val snapshot = BoundSessionSnapshot(binding.serverUrl, binding.ledgerId,
            requireNotNull(OutboxOwnerIdentity.parseOrNull(binding.ownerKey)), "synthetic-session",
            binding.sessionGeneration, binding.bindingRevision)
        val bound = BoundLedgerRequest(f.service, snapshot) { snapshot }
        val start = CompletableDeferred<Unit>()
        val tasks = listOf(f.fixture.outbox, second).map { queue -> async(Dispatchers.IO) {
            start.await()
            queue.enqueueOriginalCreation(bound, f.intent(f.key))
        } }
        start.complete(Unit)
        val ids = tasks.awaitAll()
        assertEquals(ids.first(), ids.last())
        val original = f.fixture.stored().single()
        assertTrue(repository.create(binding, f.request.copy(name = "改过的名称"), f.key).isFailure)
        assertTrue(repository.create(binding, f.request.copy(debtPublicIds = listOf("debt-c")), f.key).isFailure)
        assertEquals(listOf(original), f.fixture.stored())
        val otherKey = UUID.randomUUID().toString()
        val otherId = repository.create(binding, f.request, otherKey).getOrThrow()
        assertNotEquals(ids.first(), otherId)
        assertEquals(original["payload"], f.fixture.stored().last()["payload"])
        assertEquals(original, f.fixture.stored().first())
        f.fixture.role("viewer")
        assertTrue(repository.create(requireNotNull(repository.currentAccess()).binding, f.request, UUID.randomUUID().toString()).isFailure)
        f.fixture.switchLedger()
        assertTrue(repository.create(binding, f.request, UUID.randomUUID().toString()).isFailure)
        assertTrue(repository.observeCreations(binding, originalId = ids.first()).first().isEmpty())
        assertEquals(2, f.fixture.stored().size)
        assertTrue(f.calls.isEmpty())
    }

    @Test fun explicitIdRetainsUnknownAbandonedAndMalformedOriginalsWithoutCrossingDefaultGoalTypes() = runBlocking {
        val repository = f.fixture.reopen().goalEditRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        for ((wire, status) in listOf("future_goal_state" to PendingMutationStatus.Unknown,
            "abandoned" to PendingMutationStatus.Abandoned, "pending" to PendingMutationStatus.Pending)) {
            val key = UUID.randomUUID().toString()
            val row = f.intent(key).toEntity(debtOutboxBinding(binding), Instant.now(f.fixture.clock).toString())
                .copy(status = wire, payload = if (wire == "pending") "{" else f.adapters.goalCreateAdapter.toJson(f.request))
            val id = f.fixture.pendingDao.insert(row)
            val selected = repository.observeCreations(binding, originalId = id).first().single()
            assertEquals(id, selected.row.id)
            assertEquals(status, selected.row.status)
            assertFalse(selected.canRetry)
            if (wire == "pending") assertNull(selected.request)
            else assertEquals(listOf("debt-b", "debt-a"), selected.request?.debtPublicIds)
            assertEquals(selected, repository.originalCreation(binding, key).getOrThrow())
        }
        val spendingId = repository.create(binding, GoalDraft("旅行", "2026-09", 1200, null, "JPY"),
            UUID.randomUUID().toString()).getOrThrow()
        assertEquals(listOf(spendingId), repository.observeCreations(binding).first().map { it.row.id })
        assertTrue(repository.observeCreations(binding, goalType = "debt_repayment").first().isEmpty())
        val original = f.fixture.stored().first()
        assertTrue(runCatching { repository.observeCreations(binding, f.key, originalId = original["id"]?.toLong()) }.isFailure)
        assertEquals(4, f.fixture.stored().size)
    }

    @Test fun acceptedDebtCreationRetiresOldGoalMembershipAcrossOfflineRoomReopen() = runBlocking {
        val graph = f.fixture.reopen()
        val repository = graph.goalEditRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        assertEquals("old-debt-goal", graph.reportsRepository.debtGoals().getOrThrow().single().publicId)
        graph.reportsRepository.goal("old-debt-goal").getOrThrow()
        repository.create(binding, f.request, f.key).getOrThrow()
        assertEquals(1, f.drain().done)
        f.offline = true
        val reopened = f.fixture.reopen()
        assertTrue(reopened.reportsRepository.debtGoals().isFailure)
        assertTrue(reopened.reportsRepository.goal("old-debt-goal").isFailure)
        assertTrue(reopened.reportsRepository.goal("created-debt-goal").isFailure)
        val original = requireNotNull(reopened.goalEditRepository.originalCreation(binding, f.key).getOrThrow())
        assertTrue(original.isDone)
        assertEquals("created-debt-goal", original.confirmed?.publicId)
        assertEquals(listOf("debt-b", "debt-a"), original.request?.debtPublicIds)
    }

    @Test fun stopRetainsAnUnacknowledgedDebtOriginalAcrossReopenAndCannotOverwriteAConcurrentClaim() = runBlocking {
        var repository = f.fixture.reopen().goalEditRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        val id = repository.create(binding, f.request, f.key).getOrThrow()
        val original = f.fixture.stored().single()
        f.loseRemoteAck = true
        assertEquals(1, f.drain().failures)
        val failed = requireNotNull(repository.originalCreation(binding, f.key).getOrThrow())
        repository.recoverCreation(binding, failed, drop = true).getOrThrow()
        repository = f.fixture.reopen().goalEditRepository
        val stopped = requireNotNull(repository.originalCreation(binding, f.key).getOrThrow())
        assertEquals(PendingMutationStatus.Abandoned, stopped.row.status)
        assertFalse(stopped.canRetry)
        assertEquals(id, repository.create(binding, f.request, f.key).getOrThrow())
        for (field in listOf("payload", "targetId", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "serverUrl")) {
            assertEquals(field, original[field], f.fixture.stored().single()[field])
        }
        assertEquals(0, f.drain().done)
        assertEquals(1, f.calls.size)
        assertEquals(1, f.accepted.size)

        val nextKey = UUID.randomUUID().toString()
        val nextId = repository.create(binding, f.request, nextKey).getOrThrow()
        val pending = requireNotNull(repository.originalCreation(binding, nextKey).getOrThrow())
        assertEquals(1, f.fixture.pendingDao.markInFlightIfPending(nextId, "pending", "in_flight", "attempt"))
        assertEquals(0, f.fixture.pendingDao.abandonOriginalCommand(nextId, binding.ownerKey, binding.ledgerId, "pending", "stop"))
        assertTrue(repository.recoverCreation(binding, pending, drop = true).isFailure)
        assertEquals(PendingMutationStatus.InFlight,
            repository.observeCreations(binding, originalId = nextId).first().single().row.status)
        assertEquals(2, f.fixture.stored().size)
    }
}

private class DebtCreationConnectedFixture {
    val adapters = OutboxAdapterGraph()
    val key = UUID.randomUUID().toString()
    val request = GoalCreateRequestDto("还清欠款", goalType = "debt_repayment", debtPublicIds = listOf("debt-b", "debt-a"))
    val calls = mutableListOf<Pair<GoalCreateRequestDto, String>>()
    val accepted = mutableMapOf<String, GoalDto>()
    var loseRemoteAck = false
    var offline = false
    var laterRemaining = 1200L
    lateinit var service: ApiService
    val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext()) { delegate ->
        object : ApiService by delegate {
            override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?, idempotencyKey: String?): GoalDto {
                val key = requireNotNull(idempotencyKey)
                calls += request to key
                check(calls.first { it.second == key }.first == request) { "Replay changed the original selection" }
                val receipt = accepted.getOrPut(key) { debtCreationRoomReceipt(request, laterRemaining) }
                if (loseRemoteAck) throw IOException("Synthetic remote acknowledgement lost after creation")
                return receipt
            }
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?): GoalListResponseDto {
                if (offline) throw ConnectException("offline")
                return GoalListResponseDto(listOf(debtCreationRoomReceipt(request).copy(publicId = "old-debt-goal")))
            }
            override suspend fun goal(publicId: String, timezone: String?): GoalDto {
                if (offline) throw ConnectException("offline")
                return debtCreationRoomReceipt(request).copy(publicId = publicId)
            }
        }.also { service = it }
    }
    fun intent(key: String) = PendingMutationIntent(PendingMutationType.CreateGoal, "goal_create:$key",
        adapters.goalCreateAdapter.toJson(request), 0, key)
    suspend fun drain() = OutboxDrainEngine(fixture.outbox, listOf(CreateGoalDispatcher({ service },
        adapters.goalCreateAdapter, adapters.goalReceiptAdapter, fixture.graph.reportsRepository::invalidateGoalReadsAfterDelivery)),
        maxAttempts = 1, now = fixture.clock::millis).drainOnce()
}

private fun debtCreationRoomReceipt(request: GoalCreateRequestDto, remaining: Long = 1200) = GoalDto(
    "created-debt-goal", "correction-ledger", request.name, "debt_repayment", "monthly", null, null, null, null, null, null,
    "in_progress", "active", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 1, null,
    debtRepayment = DebtRepaymentEvaluationDto(1, "in_progress", false, linkedDebts = request.debtPublicIds.orEmpty().map {
        DebtGoalLinkViewDto(it, "open", "i_owe", "external", "原欠款对象", 1200, remaining, "JPY")
    }, voidedDebtPublicIds = emptyList()),
)

private fun debtOutboxBinding(binding: LogicalSessionBinding) = OutboxBinding(binding.serverUrl, binding.ledgerId,
    requireNotNull(OutboxOwnerIdentity.parseOrNull(binding.ownerKey)))
