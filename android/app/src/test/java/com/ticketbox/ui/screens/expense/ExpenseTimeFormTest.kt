package com.ticketbox.ui.screens.expense

import com.ticketbox.data.remote.dto.LedgerCalendarDto
import java.time.ZoneId
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class ExpenseTimeFormTest {
    private val rule = LedgerCalendarDto("owner", 2, "Asia/Shanghai", "explicit", "2026-09-20T00:00:00Z")
    private fun form(instant: String = "2026-11-01T06:30:00Z") =
        ExpenseTimeForm.initial(instant, null, rule, ZoneId.of("America/New_York"))

    @Test fun unchangedLaterFoldKeepsOriginalInstantAndOffsetAcrossSavedDraft() {
        val restored = requireNotNull(readExpenseTimeForm(form().toSavedJson())).resolve()
        assertEquals("2026-11-01T06:30:00Z", restored.instant)
        assertEquals(-18000, restored.input?.sourceUtcOffsetSeconds)
    }

    @Test fun gapKeepsRawInputAndOffersNoInventedInstant() {
        val raw = form().copy(date = "2026-03-08", time = "02:30", offsetSeconds = null, changed = true)
        val restored = requireNotNull(readExpenseTimeForm(raw.toSavedJson()))
        assertEquals(raw, restored)
        assertNotNull(restored.resolve().error)
        assertNull(restored.resolve().instant)
    }

    @Test fun foldRequiresExplicitChoiceAndBothChoicesAreRepresentable() {
        val raw = form().copy(time = "01:30", offsetSeconds = null, changed = true)
        assertNotNull(raw.resolve().error)
        assertEquals(listOf(-14400, -18000), raw.validOffsets().map { it.totalSeconds })
        assertEquals("2026-11-01T05:30:00Z", raw.copy(offsetSeconds = -14400).resolve().instant)
        assertEquals("2026-11-01T06:30:00Z", raw.copy(offsetSeconds = -18000).resolve().instant)
    }

    @Test fun dateOnlyKeepsCapturedRevisionWithoutCreatingClockTime() {
        val later = rule.copy(revision = 3, timezoneName = "UTC")
        val captured = form().withPrecision("date_only", later).resolve()
        assertNull(captured.instant)
        assertEquals(2L, captured.input?.calendarRevision)
        assertEquals("2026-11-01", captured.input?.accountingDate)
        assertNull(captured.input?.sourceUtcOffsetSeconds)
    }

    @Test fun absentRuleKeepsLegacyInstantButDateOnlyCannotSilentlyDowngrade() {
        val legacy = ExpenseTimeForm.initial("2026-11-01T06:30:00Z", null, null, ZoneId.of("America/New_York"))
        assertEquals("2026-11-01T06:30:00Z", legacy.resolve().instant)
        assertNull(legacy.resolve().input)
        val dateOnly = requireNotNull(readExpenseTimeForm(legacy.withPrecision("date_only", null).toSavedJson()))
        assertEquals("date_only", dateOnly.precision)
        assertNotNull(dateOnly.resolve().error)
        assertNull(dateOnly.resolve().instant)
    }

    @Test fun invalidZoneRemainsEditableAndIsNotReportedAsADstGap() {
        val invalid = form().copy(sourceZone = "invalid/place", changed = true)
        assertEquals(com.ticketbox.R.string.calendar_input_invalid_zone, invalid.resolve().error)
        assertEquals(invalid, readExpenseTimeForm(invalid.toSavedJson()))
    }
}
