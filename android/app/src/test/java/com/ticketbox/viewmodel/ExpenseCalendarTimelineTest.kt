package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseCalendarTimelineTest {
    @Test fun accountingTimeIsOneReadableChangeAndOldRevisionsStillRead() {
        val original = ExpenseRevision("revision-2", 2, "correction", "修正日期",
            listOf("accounting_time", "expense_time"),
            mapOf("accounting_time" to mapOf("precision" to "date_only", "accounting_date" to "2026-04-30")),
            mapOf("accounting_time" to mapOf("precision" to "date_only", "accounting_date" to "2026-05-01")),
            "我", "手机", "2026-09-20T00:00:00Z")
        val change = listOf(original).toTimelineEntries(CurrencyCode.CNY).single().changes.single()
        assertEquals(UiText.compound(listOf(UiText.raw("2026-04-30"), UiText.res(R.string.calendar_date_only_label)), " · "), change.before)
        assertEquals(UiText.compound(listOf(UiText.raw("2026-05-01"), UiText.res(R.string.calendar_date_only_label)), " · "), change.after)
        val historical = original.copy(changedFields = listOf("expense_time"), before = mapOf("expense_time" to null),
            after = mapOf("expense_time" to "2026-05-01T12:00:00Z"))
        assertEquals(1, listOf(historical).toTimelineEntries(CurrencyCode.CNY).single().changes.size)
    }
}
