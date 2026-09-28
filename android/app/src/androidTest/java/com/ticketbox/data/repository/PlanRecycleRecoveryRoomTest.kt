package com.ticketbox.data.repository

import androidx.test.core.app.ApplicationProvider
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.RecycleBinItemDto
import com.ticketbox.data.remote.dto.RecycleBinListResponseDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreRequestDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreResponseDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomePlanStatus
import java.net.UnknownHostException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Uses the actual recycle-bin entry and disk query owners; only server transport is synthetic. */
class PlanRecycleRecoveryRoomTest {
    private var goal = GoalDto("goal-1", "income-ledger", "九月消费目标", "spending_limit", "monthly", "2026-09",
        null, 2000, null, null, null, "unavailable", "archived", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z",
        3, "2026-09-02T00:00:00Z", homeCurrencyCode = "CNY")
    private val restores = mutableListOf<RecycleBinRestoreRequestDto>()
    private val fixture: IncomePlanConnectedFixture = IncomePlanConnectedFixture(ApplicationProvider.getApplicationContext()) { delegate ->
        object : ApiService by delegate {
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?): GoalListResponseDto {
                if (fixture.network.failReads) throw UnknownHostException("Synthetic offline goal read")
                return GoalListResponseDto(if (includeArchived || goal.status == "active") listOf(goal) else emptyList())
            }
            override suspend fun goal(publicId: String, timezone: String?): GoalDto {
                if (fixture.network.failReads) throw UnknownHostException("Synthetic offline goal detail")
                return goal.also { check(it.publicId == publicId) }
            }
            override suspend fun recycleBin() = RecycleBinListResponseDto(listOf(
                RecycleBinItemDto("income_plan", "收入计划", "income-1", "九月收入", "已归档", retentionLabel = "可恢复",
                    expectedRowVersion = fixture.network.current.rowVersion.toInt(), restoreIntentMonth = "2026-09"),
                RecycleBinItemDto("goal", "消费目标", "goal-1", goal.name, "已归档", retentionLabel = "可恢复",
                    expectedRowVersion = goal.rowVersion.toInt()),
            ), 0)
            override suspend fun restoreRecycleBinItem(request: RecycleBinRestoreRequestDto): RecycleBinRestoreResponseDto {
                restores += request
                when (request.kind) {
                    "income_plan" -> fixture.network.current = fixture.network.current.copy(status = "active", rowVersion = 4, archivedAt = null)
                    "goal" -> goal = goal.copy(status = "active", rowVersion = 4, archivedAt = null)
                    else -> error("Unexpected restore kind")
                }
                return RecycleBinRestoreResponseDto("已恢复")
            }
        }
    }

    @After fun close() = fixture.close()

    @Test fun acceptedIncomeRestoreRetiresArchivedReadsAcrossRoomReopenWithoutTouchingOriginalDraft() = runBlocking {
        val graph = fixture.reopen()
        val income = graph.incomePlanRepository
        val binding = requireNotNull(income.observeActiveLedgerAccess().first()).binding
        val original = income.listActive(binding).getOrThrow().plans.single()
        income.enqueueUpdate(binding, original, IncomePlanPatch("2026-09", original.rowVersion, amountCents = 12345), CurrencyCode.CNY).getOrThrow()
        val pending = fixture.stored()
        fixture.network.current = fixture.network.current.copy(status = "archived", archivedAt = "2026-09-02T00:00:00Z")
        income.listIncluding(binding, IncomePlanStatus.ARCHIVED).getOrThrow()
        income.history(binding, "income-1", null).getOrThrow()
        val item = graph.ledgerRepository.refreshRecycleBin().getOrThrow().items.single { it.kind == "income_plan" }
        graph.ledgerRepository.restoreRecycleBinItem(item).getOrThrow()
        assertEquals("active", fixture.network.current.status)
        assertEquals(3, restores.single().expectedRowVersion)
        assertEquals("2026-09", restores.single().intentMonth)
        fixture.network.failReads = true
        val reopened = fixture.reopen().incomePlanRepository
        assertTrue("Restored income still appears archived after an offline reopen", reopened.listIncluding(binding, IncomePlanStatus.ARCHIVED).isFailure)
        assertTrue(reopened.history(binding, "income-1", null).isFailure)
        assertEquals(pending, fixture.stored())
    }

    @Test fun acceptedGoalRestoreRetiresArchivedListAndDetailAcrossRoomReopen() = runBlocking {
        val graph = fixture.reopen()
        graph.reportsRepository.goals("2026-09", includeArchived = true).getOrThrow()
        graph.reportsRepository.goal("goal-1").getOrThrow()
        val item = graph.ledgerRepository.refreshRecycleBin().getOrThrow().items.single { it.kind == "goal" }
        graph.ledgerRepository.restoreRecycleBinItem(item).getOrThrow()
        assertEquals("active", goal.status)
        fixture.network.failReads = true
        val reopened = fixture.reopen().reportsRepository
        assertTrue("Restored goal still appears archived after an offline reopen", reopened.goals("2026-09", includeArchived = true).isFailure)
        assertTrue(reopened.goal("goal-1").isFailure)
        assertTrue(fixture.stored().isEmpty())
    }

    @Test fun incomeRestoreFromPreviousAccountCannotBeSentUnderTheNewAccount() = runBlocking { rejectPreviousAccountItem("income_plan") }
    @Test fun goalRestoreFromPreviousAccountCannotBeSentUnderTheNewAccount() = runBlocking { rejectPreviousAccountItem("goal") }

    private suspend fun rejectPreviousAccountItem(kind: String) {
        val graph = fixture.reopen()
        fixture.network.current = fixture.network.current.copy(status = "archived", archivedAt = "2026-09-02T00:00:00Z")
        val item = graph.ledgerRepository.refreshRecycleBin().getOrThrow().items.single { it.kind == kind }
        fixture.changeAccount()
        val result = graph.ledgerRepository.restoreRecycleBinItem(item)
        assertTrue("A restore selected by the previous account was sent using the current account", result.isFailure)
        assertTrue(restores.isEmpty())
        assertTrue(fixture.stored().isEmpty())
    }
}
