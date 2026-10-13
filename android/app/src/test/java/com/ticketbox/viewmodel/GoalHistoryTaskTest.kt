package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.GoalDefinition
import com.ticketbox.domain.model.GoalHistoryPage
import com.ticketbox.domain.model.GoalRevision
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class GoalHistoryTaskTest {
    @Test fun laterPageKeepsTheOldestReadTimeAndRefreshStartsANewReadRange() = runTest {
        val expectedBinding = LogicalSessionBinding("https://goal.example", "household", "owner", "session", "revision")
        var version = 4L
        val reads = mutableListOf<Long?>()
        val reports = object : ReportsActions by RecordingSpendingGoalActions() {
            override suspend fun goalHistory(publicId: String, beforeVersion: Long?, binding: LogicalSessionBinding): Result<ReadSnapshot<GoalHistoryPage>> {
                assertEquals(expectedBinding, binding)
                assertEquals("goal", publicId)
                reads += beforeVersion
                val row = GoalRevision(version, "edit", "2026-09-20T00:00:00Z",
                    GoalDefinition("原目标", "spending", "monthly", "2026-09", null, 1200, "JPY", "active"))
                return Result.success(ReadSnapshot(GoalHistoryPage(listOf(row), if (version == 4L) 4 else null),
                    if (version == 4L) "2026-09-28T10:00:00Z" else "2026-09-29T10:00:00Z", version == 3L))
            }
        }
        var state = GoalHistoryState()
        val task = GoalHistoryTask(reports, backgroundScope, { expectedBinding to "goal" }, { state = it })
        task.open()
        runCurrent()
        version = 3
        task.more()
        runCurrent()
        assertEquals(listOf(4L, 3L), state.items.map { it.rowVersion })
        assertEquals("2026-09-28T10:00:00Z", state.fetchedAt)
        assertTrue(state.fromCache)
        task.refresh()
        runCurrent()
        assertEquals(listOf(3L), state.items.map { it.rowVersion })
        assertEquals("2026-09-29T10:00:00Z", state.fetchedAt)
        assertEquals(listOf(null, 4L, null), reads)
    }
}
