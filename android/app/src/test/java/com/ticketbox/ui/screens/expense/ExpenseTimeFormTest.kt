package com.ticketbox.ui.screens.expense

import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.domain.model.RecognitionTimeCandidate
import java.time.ZoneId
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class ExpenseTimeFormTest {
    private val rule = LedgerCalendarDto("owner", 2, "Asia/Shanghai", "explicit", "2026-09-20T00:00:00Z")
    private fun form(instant: String = "2026-11-01T06:30:00Z") =
        ExpenseTimeForm.initial(instant, null, rule, ZoneId.of("America/New_York"))

    @Test fun summaryNamesTheZoneOnlyWhenItIsNotTheDeviceZone() {
        val recorded = form()
        assertEquals("${recorded.date} · ${recorded.time}", recorded.summary(deviceZone = recorded.sourceZone))
        assertEquals("${recorded.date} · ${recorded.time} · ${recorded.sourceZone}", recorded.summary(deviceZone = "Asia/Tokyo"))
        val dateOnly = recorded.withPrecision("date_only", rule)
        assertEquals(dateOnly.date, dateOnly.summary(deviceZone = "Asia/Tokyo"))
    }

    @Test fun unchangedLaterFoldKeepsOriginalInstantAndOffsetAcrossSavedDraft() {
        val restored = requireNotNull(readExpenseTimeForm(form().toSavedJson())).resolve()
        assertEquals("2026-11-01T06:30:00Z", restored.instant)
        assertEquals(-18000, restored.input?.sourceUtcOffsetSeconds)
    }

    @Test fun unchangedUnknownEditDoesNotInventTimeOrValidateEmptySourceFields() {
        val unknown = ExpenseTimeForm.initial(null, null, rule, ZoneId.of("UTC"))
        val edit = unknown.resolveEdit(null)
        assertNull(edit.error)
        assertNull(edit.instant)
        assertNull(edit.input)
        assertEquals("date_only", unknown.withPrecision("date_only", rule).copy(date = "2026-09-20").resolveEdit(null).input?.precision)
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
    @Test fun printedOffsetChoiceSurvivesDraftRestoreWithoutInventingARegion() {
        val candidate = RecognitionTimeCandidate("candidate", "支付时间", "精确到分", "支付时间 2026-11-01 01:30-05:00",
            "2026-11-01T01:30", "minute", null, -18000, true,
            evidencePublicId = "original-fact", parserVersion = "receipt-fields-v3", source = "image")
        val original = form()
        val chosen = original.withRecognizedTime(candidate)
        val restored = requireNotNull(readExpenseTimeForm(chosen.toSavedJson()))
        assertEquals("original-fact", restored.recognitionChoice?.evidencePublicId)
        assertEquals("candidate", restored.recognitionChoice?.candidateId)
        assertEquals(chosen.recognitionChoice, restored.copy(time = "01:40").recognitionChoice)
        assertNull(original.recognitionChoice)
        val resolved = restored.resolveEdit(original.originalInstant)
        assertEquals("2026-11-01T06:30:00Z", resolved.instant)
        assertEquals(-18000, resolved.input?.sourceUtcOffsetSeconds)
        assertNull(resolved.input?.sourceTimezone)
        assertEquals(original.calendarRevision, resolved.input?.calendarRevision)
        assertEquals(false, original.changed)
        val day = original.withRecognizedTime(candidate.copy(localValue = "2026-10-31", precision = "date_only",
            sourceTimezone = "America/New_York", sourceUtcOffsetSeconds = null))
        assertNull(day.resolve().instant)
        assertEquals("2026-10-31", day.resolve().input?.userLocalDate)
        assertEquals("America/New_York", requireNotNull(readExpenseTimeForm(day.toSavedJson())).resolve().input?.sourceTimezone)
        val offsetDay = chosen.withPrecision("date_only", rule).resolve()
        assertNull(offsetDay.error)
        assertNull(offsetDay.input?.sourceTimezone)
        assertNull(offsetDay.input?.sourceUtcOffsetSeconds)
    }

}
