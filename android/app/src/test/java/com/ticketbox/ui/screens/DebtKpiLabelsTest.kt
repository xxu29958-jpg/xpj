package com.ticketbox.ui.screens

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * ADR-0049 §7.0 / 8e-6b: the external-debt payoff-date parser ([parsePayoffYearMonth]).
 * Pure JVM — pins the month-granularity rendering (drop the day to avoid false precision)
 * and the honest-fallback contract (unparseable / illegal → null → "数据不足" copy, never a fake date).
 */
class DebtKpiLabelsTest {

    @Test
    fun parsesYearAndMonthDroppingTheDay() {
        assertEquals(2026 to 9, parsePayoffYearMonth("2026-09-01"))
        assertEquals(2026 to 12, parsePayoffYearMonth("2026-12-31"))
        assertEquals(2027 to 1, parsePayoffYearMonth("2027-01-15"))
    }

    @Test
    fun returnsNullForUnparseableOrIllegalMonth() {
        assertNull(parsePayoffYearMonth(""))
        assertNull(parsePayoffYearMonth("2026"))
        assertNull(parsePayoffYearMonth("notadate"))
        assertNull(parsePayoffYearMonth("abcd-09-01")) // non-numeric year
        assertNull(parsePayoffYearMonth("2026-13-01")) // month above range
        assertNull(parsePayoffYearMonth("2026-00-01")) // month below range
    }
}
