package com.ticketbox.data.repository

import androidx.test.core.app.ApplicationProvider
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import java.net.ConnectException
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Real disk Room and the production repository graph; only HTTP transport is synthetic. */
class GoalQuerySnapshotRoomTest {
    private var offline = false
    private val fixture: ExpenseCorrectionConnectedFixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext()) { delegate ->
        object : ApiService by delegate {
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?): GoalListResponseDto {
                if (offline) throw ConnectException("offline")
                return GoalListResponseDto(listOf(goal()))
            }
            override suspend fun goal(publicId: String, timezone: String?): GoalDto {
                if (offline) throw ConnectException("offline")
                error("The scenario must not prefetch a detail before going offline")
            }
        }
    }

    @After fun close() = fixture.close()

    @Test fun diskReopenRestoresUnvisitedDetailAndClearKeepsEveryOriginalCommandByte() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        val list = graph.reportsRepository.goals("2026-09", expectedBinding = binding, timezone = "Asia/Tokyo").getOrThrow()
        graph.expenseRepository.submitCorrection(binding, fixture.network.current.toDomain(),
            ExpenseCorrectionDraft("清理查询快照前的原提交", note = "未发送的原内容")).getOrThrow()
        val original = fixture.stored()
        assertTrue(original.isNotEmpty())
        offline = true
        val reopened = fixture.reopen()
        val detail = reopened.reportsRepository.goal("goal-jpy", binding, "Asia/Tokyo").getOrThrow()
        assertTrue(detail.fromCache)
        assertEquals(list.fetchedAt, detail.fetchedAt)
        assertEquals(list.value.single(), detail.value)
        assertEquals("JPY", detail.value.homeCurrencyCode)
        assertNull(detail.value.spentAmountCents)
        assertNull(detail.value.progressPercent)
        reopened.expenseRepository.clearLocalCache()
        assertEquals(original, fixture.stored())
        assertTrue(reopened.reportsRepository.goal("goal-jpy", binding, "Asia/Tokyo").isFailure)
        assertTrue(reopened.reportsRepository.goals("2026-09", expectedBinding = binding, timezone = "Asia/Tokyo").isFailure)
    }

    @Test fun replacementBindingCannotReadAnOldGoalSnapshot() = runBlocking {
        val graph = fixture.reopen()
        graph.reportsRepository.goals("2026-09").getOrThrow()
        val before = fixture.stored()
        fixture.switchLedger()
        offline = true
        assertTrue(graph.reportsRepository.goal("goal-jpy").isFailure)
        assertEquals(before, fixture.stored())
    }

    private fun goal(): GoalDto = GoalDto(
        publicId = "goal-jpy", ledgerId = requireNotNull(fixture.graph.reportsRepository.dashboardAccess()).binding.ledgerId,
        name = "旅行限额", goalType = "spending_limit", period = "monthly",
        month = "2026-09", category = null, targetAmountCents = 1200, spentAmountCents = null,
        remainingAmountCents = null, progressPercent = null, progressState = "unavailable", status = "active",
        createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 2,
        archivedAt = null, homeCurrencyCode = "JPY",
    )
}
