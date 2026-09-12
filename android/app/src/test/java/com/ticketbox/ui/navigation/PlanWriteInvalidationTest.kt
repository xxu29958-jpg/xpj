package com.ticketbox.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Test

/** The plan-write composition invalidates financial reads for every save,
 *  but only advice-input saves (income plan /
 *  recurring) drop the advice cache — the monthly-budget row is not an
 *  advisor input (_inputs_builder.py), so a budget save must preserve it. */
class PlanWriteInvalidationTest {
    @Test
    fun budgetSavePreservesAdviceCache() {
        val shellState = MainShellState()
        val initialRevision = shellState.financialDataRevision
        var invalidations = 0

        markPlanWriteCompleted(shellState, invalidatesAdvice = false) { invalidations += 1 }

        assertEquals(initialRevision + 1, shellState.financialDataRevision)
        assertEquals(0, invalidations)
    }

    @Test
    fun incomePlanSaveInvalidatesAdviceCache() {
        val shellState = MainShellState()
        val initialRevision = shellState.financialDataRevision
        var invalidations = 0

        markPlanWriteCompleted(shellState, invalidatesAdvice = true) { invalidations += 1 }

        assertEquals(initialRevision + 1, shellState.financialDataRevision)
        assertEquals(1, invalidations)
    }
}
