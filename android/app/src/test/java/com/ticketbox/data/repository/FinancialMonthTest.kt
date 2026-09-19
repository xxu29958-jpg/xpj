package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.LedgerCalendarDto
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import kotlinx.coroutines.test.runTest
import org.junit.Test
import kotlin.test.assertEquals

class FinancialMonthTest {
    private val binding = LogicalSessionBinding("https://example.test", "ledger", "owner", "session", "revision")
    private val clock = Clock.fixed(Instant.parse("2026-06-01T00:30:00Z"), ZoneId.of("Asia/Tokyo"))

    @Test fun capturedLedgerRuleOwnsMonthAcrossDeviceBoundaryAndWorksOffline() = runTest {
        val calendars = MonthCalendarFixture(binding, calendar(binding, "America/Los_Angeles"))
        assertEquals("2026-05", calendars.newTaskMonth(binding, clock))
        assertEquals(0, calendars.refreshes)
        assertEquals("2026-05", calendars.newTaskMonth(binding, clock.withZone(ZoneId.of("Pacific/Kiritimati"))))
    }

    @Test fun uncachedRuleIsFetchedBeforeDefaultAndOldServerKeepsUsableMonth() = runTest {
        val calendars = MonthCalendarFixture(binding).apply {
            response = Result.success(calendar(binding, "America/Los_Angeles"))
        }
        assertEquals("2026-05", calendars.newTaskMonth(binding, clock))
        assertEquals(1, calendars.refreshes)
        calendars.response = Result.success(null)
        assertEquals("2026-06", calendars.newTaskMonth(binding, clock))
        calendars.response = Result.failure(java.io.IOException("offline"))
        assertEquals("2026-06", calendars.newTaskMonth(binding, clock))
    }

    @Test fun anotherLogicalBindingCannotSupplyTheDefaultMonth() = runTest {
        val calendars = MonthCalendarFixture(binding, calendar(binding, "America/Los_Angeles"))
        assertEquals("2026-06", calendars.newTaskMonth(binding.copy(bindingRevision = "replacement"), clock))
        assertEquals(0, calendars.refreshes)
    }

    @Test fun omittedGoalMonthReachesServerWithoutDeviceTimezoneDefault() = runTest {
        var requestedMonth: String? = "not-called"
        val fixture = GoalReadFixture { delegate ->
            object : com.ticketbox.data.remote.ApiService by delegate {
                override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?) =
                    com.ticketbox.data.remote.dto.GoalListResponseDto(listOf(readGoalDto().copy(month = "2025-12")))
                        .also { requestedMonth = month }
            }
        }
        val result = fixture.repository.goals(timezone = "Pacific/Kiritimati").getOrThrow()
        assertEquals(null, requestedMonth)
        assertEquals("2025-12", result.value.single().month)
    }
}

internal fun calendar(binding: LogicalSessionBinding, zone: String = "America/Los_Angeles") =
    LedgerCalendarDto(binding.ledgerId, 1, zone, "explicit", "2026-01-01T00:00:00Z")

internal class MonthCalendarFixture(
    var binding: LogicalSessionBinding,
    var rule: LedgerCalendarDto? = null,
) : LedgerCalendarReader {
    var refreshes = 0
    var response: Result<LedgerCalendarDto?> = Result.success(null)
    var gate: (suspend () -> Unit)? = null
    override fun currentBinding() = binding
    override fun cached(binding: LogicalSessionBinding, revision: Long?): LedgerCalendarDto? =
        rule.takeIf { this.binding == binding }
    override suspend fun refresh(binding: LogicalSessionBinding, revision: Long?): Result<LedgerCalendarDto?> {
        refreshes += 1
        gate?.invoke()
        return response
    }
}
