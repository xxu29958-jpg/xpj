package com.ticketbox.ui.screens

import com.ticketbox.data.repository.RecurringDateEdit
import com.ticketbox.ui.screens.recurring.buildRecurringItemPatch
import com.ticketbox.ui.screens.recurring.recurringDefaultNextDate
import com.ticketbox.ui.screens.recurring.recurringDisplayDate
import com.ticketbox.ui.screens.recurring.recurringItemMeta
import com.ticketbox.ui.screens.recurring.recurringPickerMillisToDateIso
import java.time.Instant
import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** 行 meta 语义（manual 计划 vs 观察来源）与编辑器表单模型（日期、patch）。 */
class RecurringItemFormModelsTest {

    @Test
    fun manualItemWithoutOccurrencesExposesNoObservedMeta() {
        val manual = recurringItem {
            source = "manual"
            occurrenceCount = 0
            lastSeenAt = null
            nextExpectedDate = null
        }
        val meta = recurringItemMeta(manual)
        assertNull(meta.observedCount)
        assertNull(meta.lastObservedDate)
        assertNull(meta.nextExpectedDate)
        assertNull(meta.anomalyDeltaPercent)
    }

    @Test
    fun observedItemExposesCountAndLastObservedDate() {
        val observed = recurringItem {
            source = "candidate"
            occurrenceCount = 4
            lastSeenAt = "2026-08-15T08:30:00Z"
            anomalyStatus = "higher_than_average"
            amountDeltaPercent = 23
        }
        val meta = recurringItemMeta(observed)
        assertEquals(4, meta.observedCount)
        assertEquals("2026-08-15", meta.lastObservedDate)
        assertEquals(23, meta.anomalyDeltaPercent)
    }

    @Test
    fun defaultNextDateSuggestsSameDayNextMonth() {
        assertEquals("2026-09-30", recurringDefaultNextDate(LocalDate.of(2026, 8, 30)))
        // 月末回退：1 月 31 日 → 2 月最后一天（2026 非闰年）。
        assertEquals("2026-02-28", recurringDefaultNextDate(LocalDate.of(2026, 1, 31)))
    }

    @Test
    fun pickerMillisRoundTripsToUtcDateIso() {
        val millis = Instant.parse("2026-09-15T00:00:00Z").toEpochMilli()
        assertEquals("2026-09-15", recurringPickerMillisToDateIso(millis))
    }

    @Test
    fun displayDateFormatsIsoAndFallsBackToRaw() {
        assertEquals("2026年9月15日", recurringDisplayDate("2026-09-15"))
        assertEquals("2026年9月15日", recurringDisplayDate("2026-09-15T10:20:00Z"))
        assertEquals("not-a-date", recurringDisplayDate("not-a-date"))
        assertEquals("", recurringDisplayDate(null))
    }

    @Test
    fun patchIsNullWhenNothingChanged() {
        val baseline = recurringItem { nextExpectedDate = "2026-09-15" }
        assertNull(
            buildRecurringItemPatch(
                baseline = baseline,
                merchant = baseline.merchant,
                baselineAmountCents = baseline.baselineAmountCents,
                dateTouched = false,
                nextExpectedDate = baseline.nextExpectedDate,
            ),
        )
        // 摸过日期但选回原值：仍然是无改动。
        assertNull(
            buildRecurringItemPatch(
                baseline = baseline,
                merchant = baseline.merchant,
                baselineAmountCents = baseline.baselineAmountCents,
                dateTouched = true,
                nextExpectedDate = baseline.nextExpectedDate,
            ),
        )
    }

    @Test
    fun patchCarriesOnlyEditedFields() {
        val baseline = recurringItem {
            merchant = "房租"
            baselineAmountCents = 3000_00
            nextExpectedDate = "2026-09-15"
        }
        val patch = buildRecurringItemPatch(
            baseline = baseline,
            merchant = "房租（整租）",
            baselineAmountCents = 3000_00,
            dateTouched = false,
            nextExpectedDate = "2026-09-15",
        )
        assertEquals("房租（整租）", patch?.merchant)
        assertNull(patch?.baselineAmountCents)
        assertEquals(RecurringDateEdit.unchanged(), patch?.nextExpectedDate)
    }

    @Test
    fun patchExplicitClearDateGoesThroughChangedNull() {
        val baseline = recurringItem { nextExpectedDate = "2026-09-15" }
        val patch = buildRecurringItemPatch(
            baseline = baseline,
            merchant = baseline.merchant,
            baselineAmountCents = baseline.baselineAmountCents,
            dateTouched = true,
            nextExpectedDate = null,
        )
        assertEquals(RecurringDateEdit.changed(null), patch?.nextExpectedDate)
    }
}
