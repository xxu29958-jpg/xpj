package com.ticketbox.notification.budget

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.MonthCalendarFixture
import com.ticketbox.data.repository.calendar
import com.ticketbox.data.repository.newTaskMonth
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import kotlinx.coroutines.test.runTest
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class BudgetFinancialMonthTest {
    private val binding = LogicalSessionBinding("https://example.test", "ledger-1", "owner", "session", "revision")

    @Test fun ledgerMonthOwnsRequestAndNotificationKeyAtMonthBoundary() = runTest {
        val calendars = MonthCalendarFixture(binding, calendar(binding))
        val clock = Clock.fixed(Instant.parse("2026-06-01T00:30:00Z"), ZoneId.of("Asia/Tokyo"))
        val store = RecordingStore()
        val requested = mutableListOf<String>()
        val checker = BudgetOverspendChecker(
            source = { month -> requested += month; Result.success(budgetOf(overspentCents = 5_000).copy(month = month)) },
            store = store,
            dispatcher = { BudgetOverspendDispatchOutcome.SENT },
            runtime = BudgetOverspendRuntime({ true }, { binding.ledgerId },
                { calendars.newTaskMonth(binding, clock) }, { 0L }, activeBinding = calendars::currentBinding),
            scope = this,
        )
        checker.checkNow(binding.ledgerId)
        checker.checkNow(binding.ledgerId)
        assertEquals(listOf("2026-05"), requested)
        assertEquals(setOf("v1:budget:ledger-1:2026-05"), store.sent)
    }

    @Test fun sameLedgerReplacementDuringRuleReadCannotNotifyUnderNewPrincipal() = runTest {
        var active = binding
        var calls = 0
        val store = RecordingStore()
        val checker = BudgetOverspendChecker(
            source = { calls += 1; Result.success(budgetOf(overspentCents = 5_000)) },
            store = store,
            dispatcher = { BudgetOverspendDispatchOutcome.SENT },
            runtime = BudgetOverspendRuntime({ true }, { active.ledgerId },
                { active = binding.copy(bindingRevision = "replacement"); "2026-06" }, { 0L }, activeBinding = { active }),
            scope = this,
        )
        checker.checkNow(binding.ledgerId)
        assertEquals(0, calls)
        assertTrue(store.sent.isEmpty())
    }
}
