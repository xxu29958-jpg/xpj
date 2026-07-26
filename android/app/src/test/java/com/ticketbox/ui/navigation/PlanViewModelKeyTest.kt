package com.ticketbox.ui.navigation

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

/**
 * Pins the ledger-scoping of Plan-domain ViewModel keys: every keyed VM must
 * produce a fresh identity per ledger so a ledger switch never reuses the
 * previous ledger's budget / recurring / income state (D5; mirrors
 * [TransactionsLibraryViewModelKeyTest]).
 */
class PlanViewModelKeyTest {
    @Test
    fun keyIncludesLedgerIdAndPrefix() {
        assertEquals(
            "plan-budget-ledger-a",
            planViewModelKey("plan-budget", "ledger-a"),
        )
        assertEquals(
            "plan-income-ledger-a",
            planViewModelKey("plan-income", "ledger-a"),
        )
    }

    @Test
    fun keyDiffersAcrossLedgersForSamePrefix() {
        assertNotEquals(
            planViewModelKey("plan-budget", "ledger-a"),
            planViewModelKey("plan-budget", "ledger-b"),
        )
        assertNotEquals(
            planViewModelKey("plan-recurring", "ledger-a"),
            planViewModelKey("plan-recurring", "ledger-b"),
        )
        assertNotEquals(
            planViewModelKey("plan-income", "ledger-a"),
            planViewModelKey("plan-income", "ledger-b"),
        )
    }

    @Test
    fun nullLedgerFallsBackToNone() {
        assertEquals(
            "plan-budget-none",
            planViewModelKey("plan-budget", null),
        )
    }

    @Test
    fun planPrefixesStayDistinctWithinOneLedger() {
        val keys = listOf("plan-budget", "plan-recurring", "plan-income")
            .map { planViewModelKey(it, "ledger-a") }
        assertEquals(keys.size, keys.toSet().size)
    }
}
