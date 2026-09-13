package com.ticketbox.data.repository

import androidx.test.core.app.ApplicationProvider
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalUpdate
import java.net.ConnectException
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Actual disk Room and existing command/query owners, including the worker's verified receipt callback. */
class GoalQueryCommandRoomTest {
    private var offline = false
    private lateinit var service: ApiService
    private val adapters = OutboxAdapterGraph()
    private val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext()) { delegate ->
        object : ApiService by delegate {
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?): GoalListResponseDto {
                if (offline) throw ConnectException("offline")
                return GoalListResponseDto(listOf(originalGoal()))
            }
            override suspend fun goal(publicId: String, timezone: String?): GoalDto {
                if (offline) throw ConnectException("offline")
                return originalGoal()
            }
            override suspend fun archiveGoal(publicId: String, timezone: String?) = originalGoal().copy(status = "archived", rowVersion = 3)
            override suspend fun updateGoal(publicId: String, request: GoalUpdateRequestDto, idempotencyKey: String?, timezone: String?) =
                originalGoal().copy(targetAmountCents = request.targetAmountCents, rowVersion = request.expectedRowVersion + 1)
            override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?, idempotencyKey: String?) =
                originalGoal().copy(publicId = "created-goal", name = request.name, month = request.month,
                    category = request.category, targetAmountCents = request.targetAmountCents, rowVersion = 1)
        }.also { service = it }
    }

    @After fun close() = fixture.close()

    @Test fun archivedGoalCannotReappearAfterOfflineRoomReopenAndOriginalCommandsSurvive() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        graph.reportsRepository.goals("2026-09").getOrThrow()
        graph.expenseRepository.submitCorrection(binding, fixture.network.current.toDomain(),
            ExpenseCorrectionDraft("保留原更正", note = "未发送")).getOrThrow()
        val commands = fixture.stored()
        assertEquals("archived", graph.reportsRepository.archiveGoal("goal-jpy", binding).getOrThrow().status)
        offline = true
        val reopened = fixture.reopen()
        assertTrue(reopened.reportsRepository.goals("2026-09").isFailure)
        assertTrue(reopened.reportsRepository.goal("goal-jpy").isFailure)
        assertEquals(commands, fixture.stored())
    }

    @Test fun acceptedEditRetiresQueryCacheWithoutReplacingOriginalOutboxFields() = runBlocking {
        assertDeliveryRetiresReads(create = false)
    }

    @Test fun acceptedCreationRetiresQueryMembershipWithoutReplacingOriginalOutboxFields() = runBlocking {
        assertDeliveryRetiresReads(create = true)
    }

    private suspend fun assertDeliveryRetiresReads(create: Boolean) {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        graph.reportsRepository.goals("2026-09").getOrThrow()
        val id = if (create) graph.goalEditRepository.create(binding, GoalDraft("新目标", "2026-09", 2400, null, "JPY")).getOrThrow()
        else graph.goalEditRepository.save(binding, originalGoal().toDomain(),
            GoalUpdate(2, targetAmountCents = 2400, homeCurrencyCode = "JPY")).getOrThrow()
        val original = fixture.stored().single { it["id"] == id.toString() }
        val dispatcher = if (create) CreateGoalDispatcher({ service }, adapters.goalCreateAdapter,
            adapters.goalReceiptAdapter, graph.reportsRepository::invalidateGoalReadsAfterDelivery)
        else UpdateGoalDispatcher({ service }, adapters.goalUpdateAdapter,
            adapters.goalReceiptAdapter, graph.reportsRepository::invalidateGoalReadsAfterDelivery)
        assertEquals(1, OutboxDrainEngine(fixture.outbox, listOf(dispatcher), now = fixture.clock::millis).drainOnce().done)
        val done = fixture.stored().single { it["id"] == id.toString() }
        assertEquals("done", done["status"])
        for (field in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "serverUrl")) {
            assertEquals(field, original[field], done[field])
        }
        offline = true
        val reopened = fixture.reopen()
        assertTrue(reopened.reportsRepository.goals("2026-09").isFailure)
        assertTrue(reopened.reportsRepository.goal("goal-jpy").isFailure)
        val type = if (create) PendingMutationType.CreateGoal else PendingMutationType.UpdateGoal
        assertTrue(fixture.stored().any { it["type"] == type.wireValue && it["status"] == "done" })
    }

    private fun originalGoal() = GoalDto("goal-jpy", "correction-ledger", "日元目标", "spending_limit", "monthly", "2026-09",
        null, 1200, null, null, null, "unavailable", "active", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 2, null,
        homeCurrencyCode = "JPY")
}
