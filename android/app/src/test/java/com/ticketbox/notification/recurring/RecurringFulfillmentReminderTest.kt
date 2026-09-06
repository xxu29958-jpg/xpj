package com.ticketbox.notification.recurring

import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertNull

class RecurringFulfillmentReminderTest {
    @Test
    fun satisfiedOccurrenceDoesNotRemindFromTheUnchangedScheduleAnchor() {
        val today = LocalDate.parse("2026-09-06")
        val paid = recurringItemFixture(nextExpectedDate = "2026-09-05").copy(nextDueDate = "2026-10-05")
        assertNull(RecurringReminderPolicy().evaluate(today, paid))
        assertNull(RecurringReminderPolicy().evaluate(today, paid.copy(nextDueDate = null)))
    }
}
