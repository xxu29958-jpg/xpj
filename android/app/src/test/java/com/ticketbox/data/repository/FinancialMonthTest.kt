package com.ticketbox.data.repository

import com.ticketbox.domain.model.LedgerCalendar
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import kotlinx.coroutines.test.runTest
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class FinancialMonthTest {
    private val binding = LogicalSessionBinding("https://example.test", "ledger", "owner", "session", "revision")
    private val clock = Clock.fixed(Instant.parse("2026-06-01T00:30:00Z"), ZoneId.of("Asia/Tokyo"))

    @Test fun currentPresentationRefreshesOwnerRuleAndOnlyUsesCacheAfterFailure() = runTest {
        val calendars = MonthCalendarFixture(binding, calendar(binding, "Asia/Shanghai")).apply {
            response = Result.success(calendar(binding, "America/Los_Angeles"))
        }
        assertEquals("2026-05-31", calendars.refreshedLedgerDate(binding, clock).getOrThrow().toString())
        calendars.response = Result.failure(java.io.IOException("offline"))
        assertEquals("2026-06-01", calendars.refreshedLedgerDate(binding, clock).getOrThrow().toString())
        calendars.response = Result.success(null)
        assertEquals(null, calendars.refreshedLedgerDate(binding, clock).getOrThrow())
    }

    @Test fun capturedLedgerRuleOwnsMonthAcrossDeviceBoundaryAndWorksOffline() = runTest {
        val calendars = MonthCalendarFixture(binding, calendar(binding, "America/Los_Angeles"))
        assertEquals("2026-05", calendars.newTaskMonth(binding, clock).getOrThrow())
        assertEquals(0, calendars.refreshes)
        assertEquals("2026-05", calendars.newTaskMonth(binding, clock.withZone(ZoneId.of("Pacific/Kiritimati"))).getOrThrow())
    }

    @Test fun uncachedRuleDistinguishesKnownMonthUnsupportedAndReadFailure() = runTest {
        val calendars = MonthCalendarFixture(binding).apply {
            response = Result.success(calendar(binding, "America/Los_Angeles"))
        }
        assertEquals("2026-05", calendars.newTaskMonth(binding, clock).getOrThrow())
        assertEquals(1, calendars.refreshes)
        calendars.response = Result.success(null)
        assertEquals(null, calendars.newTaskMonth(binding, clock).getOrThrow())
        calendars.response = Result.failure(java.io.IOException("offline"))
        assertTrue(calendars.newTaskMonth(binding, clock).exceptionOrNull() is java.io.IOException)
    }

    @Test fun anotherLogicalBindingCannotSupplyTheDefaultMonth() = runTest {
        val calendars = MonthCalendarFixture(binding, calendar(binding, "America/Los_Angeles"))
        assertEquals(null, calendars.newTaskMonth(binding.copy(bindingRevision = "replacement"), clock).getOrThrow())
        assertEquals(0, calendars.refreshes)
    }

    @Test fun aBindingReplacementDuringTheReadCannotSupplyAMonth() = runTest {
        val calendars = MonthCalendarFixture(binding).apply {
            response = Result.success(calendar(binding))
            gate = { this.binding = binding.copy(bindingRevision = "replacement") }
        }
        assertTrue(calendars.newTaskMonth(binding, clock).isFailure)
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
    LedgerCalendar(binding.ledgerId, 1, zone, "explicit", "2026-01-01T00:00:00Z")

internal class MonthCalendarFixture(
    var binding: LogicalSessionBinding,
    var rule: LedgerCalendar? = null,
) : LedgerCalendarReader {
    var refreshes = 0
    var response: Result<LedgerCalendar?> = Result.success(null)
    var gate: (suspend () -> Unit)? = null
    override fun currentBinding() = binding
    override fun cached(binding: LogicalSessionBinding, revision: Long?): LedgerCalendar? =
        rule.takeIf { this.binding == binding }
    override suspend fun refresh(binding: LogicalSessionBinding, revision: Long?): Result<LedgerCalendar?> {
        refreshes += 1
        gate?.invoke()
        return response
    }
}
