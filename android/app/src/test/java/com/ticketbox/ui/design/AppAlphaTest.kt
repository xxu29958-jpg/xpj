package com.ticketbox.ui.design

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * A7: pin the 7 semantic alpha tiers. The values are anchored on the modes of
 * the existing ``.copy(alpha = 0.x)`` literal distribution (so residuals can be
 * migrated without changing observed opacity); pinning them keeps an accidental
 * edit from silently shifting every migrated call site's appearance.
 */
class AppAlphaTest {
    @Test
    fun tierValuesAreThePinnedAnchors() {
        assertEquals(0.10f, AppAlpha.faint)
        assertEquals(0.16f, AppAlpha.subtle)
        assertEquals(0.24f, AppAlpha.soft)
        assertEquals(0.42f, AppAlpha.medium)
        assertEquals(0.58f, AppAlpha.strong)
        assertEquals(0.72f, AppAlpha.heavy)
        assertEquals(0.86f, AppAlpha.opaque)
    }

    @Test
    fun tiersAreStrictlyAscendingAndInRange() {
        val ladder = listOf(
            AppAlpha.faint,
            AppAlpha.subtle,
            AppAlpha.soft,
            AppAlpha.medium,
            AppAlpha.strong,
            AppAlpha.heavy,
            AppAlpha.opaque,
        )
        // Strictly increasing — each tier is meaningfully more opaque than the
        // one below it (no duplicate / out-of-order anchors).
        ladder.zipWithNext().forEach { (lower, higher) ->
            assertTrue(higher > lower, "alpha tiers must strictly ascend: $lower -> $higher")
        }
        // All are real translucency in (0, 1); opaque deliberately stays < 1 so
        // it keeps a hint of background layering rather than being solid.
        ladder.forEach { value ->
            assertTrue(value > 0f && value < 1f, "alpha tier must be in (0,1): $value")
        }
    }
}
