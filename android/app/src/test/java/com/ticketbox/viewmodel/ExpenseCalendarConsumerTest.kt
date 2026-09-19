package com.ticketbox.viewmodel

import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.ExpenseAccountingTime
import com.ticketbox.domain.model.expenseLedgerMonth
import java.time.ZoneId
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class ExpenseCalendarConsumerTest {
    private val expense = requireNotNull(Moshi.Builder().add(com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory()).build().adapter(ExpenseDto::class.java).fromJson(
        """{"id":9,"public_id":"e9","status":"confirmed","source":"manual","category":"其他","duplicate_status":"none",
            "amount_cents":100,"expense_time":"2026-11-01T06:30:00Z","row_version":7,
            "created_at":"2026-11-01T06:30:00Z","updated_at":"2026-11-01T06:30:00Z"}""",
    )).toDomain()

    @Test fun noteOnlyCorrectionPreservesTheLaterFoldInstant() {
        val zone = ZoneId.of("America/New_York")
        val form = initialCorrectionFormState(expense, zone).copy(note = "note only")
        assertFalse(computeScalarChanges(expense, form, zone).expenseTimeChanged)
    }

    @Test fun storedAccountingDayWinsAcrossClientZones() {
        val fact = expense.copy(accountingTime = ExpenseAccountingTime(
            precision = "date_only", accountingDate = "2026-10-31", userLocalDate = "2026-10-31", calendarRevision = 2,
        ))
        for (zone in listOf("UTC", "Asia/Shanghai", "America/New_York")) {
            assertEquals("2026-10", expenseLedgerMonth(fact, ZoneId.of(zone)))
        }
    }

    @Test fun changingDisplayZoneDoesNotReinterpretAnOpenLegacyCorrection() {
        val form = initialCorrectionFormState(expense, ZoneId.of("America/New_York")).copy(note = "only note")
        assertFalse(computeScalarChanges(expense, form, ZoneId.of("Asia/Shanghai")).expenseTimeChanged)
    }
}
