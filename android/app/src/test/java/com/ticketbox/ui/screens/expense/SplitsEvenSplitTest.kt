package com.ticketbox.ui.screens.expense

import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * ADR-0042 Slice E-1: the splits editor's 「均分」 largest-remainder algorithm
 * ([evenSplitCents]). Deterministic by position — the first ``r`` members get
 * the extra cent, never random — so the same set always reconciles to the same
 * shares and the total is conserved exactly (no rounding drift).
 */
class SplitsEvenSplitTest {

    @Test
    fun `100 yuan over 3 gives 33_34 33_33 33_33 by position`() {
        // ¥100.00 = 10000 cents; 10000 / 3 = 3333 r 1 → first member +1.
        assertEquals(listOf(3334L, 3333L, 3333L), evenSplitCents(10000L, 3))
    }

    @Test
    fun `shares always sum back to the exact total (no drift)`() {
        for (total in listOf(0L, 1L, 7L, 100L, 9999L, 10000L, 123457L)) {
            for (count in 1..7) {
                val shares = evenSplitCents(total, count)
                assertEquals(count, shares.size, "one share per member")
                assertEquals(total, shares.sum(), "total conserved for $total / $count")
            }
        }
    }

    @Test
    fun `an even division gives equal shares with no remainder`() {
        assertEquals(listOf(2500L, 2500L, 2500L, 2500L), evenSplitCents(10000L, 4))
    }

    @Test
    fun `zero or negative member count yields an empty list`() {
        assertEquals(emptyList(), evenSplitCents(10000L, 0))
        assertEquals(emptyList(), evenSplitCents(10000L, -2))
    }

    // ADR-0042 follow-up: 均分 reserves disabled members' fixed shares so 差额→0.

    @Test
    fun `reserves a disabled member's fixed share so active shares plus fixed sum to parent`() {
        // ¥100 parent, a disabled member holds ¥30 → only ¥70 distributes over 2.
        val active = evenSplitActiveCents(parentCents = 10000L, fixedDisabledCents = 3000L, activeCount = 2)
        assertEquals(listOf(3500L, 3500L), active)
        assertEquals(10000L, active.sum() + 3000L, "active + fixed disabled = parent (差额 0)")
    }

    @Test
    fun `with no disabled reservation it matches evenSplitCents`() {
        assertEquals(evenSplitCents(10000L, 3), evenSplitActiveCents(10000L, 0L, 3))
    }

    @Test
    fun `an over-reserved fixed total clamps the distributable to zero`() {
        assertEquals(listOf(0L, 0L), evenSplitActiveCents(parentCents = 10000L, fixedDisabledCents = 12000L, activeCount = 2))
    }
}
