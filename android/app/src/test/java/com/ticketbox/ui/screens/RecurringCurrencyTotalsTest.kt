package com.ticketbox.ui.screens

import com.ticketbox.ui.screens.recurring.recurringHeroModel
import com.ticketbox.viewmodel.RecurringListLoadState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

class RecurringCurrencyTotalsTest {
    @Test
    fun `same raw integers in different currencies cannot publish the same monetary total`() {
        val first = recurringItem { publicId = "cny-plan"; baselineAmountCents = 1200 }
        val second = recurringItem { publicId = "other-plan"; baselineAmountCents = 1200 }
        val cny = recurringHeroModel(listOf(first, second), RecurringListLoadState.Loaded)
        val mixed = recurringHeroModel(listOf(first, second.copy(homeCurrencyCode = "JPY")), RecurringListLoadState.Loaded)
        assertNotEquals(cny, mixed)
        assertEquals(mapOf("CNY" to 1200L, "JPY" to 1200L), mixed.amountsByCurrency)
    }

    @Test
    fun `unknown recorded currency cannot publish a CNY monetary total`() {
        val plan = recurringItem { baselineAmountCents = 1200 }
        val cny = recurringHeroModel(listOf(plan), RecurringListLoadState.Loaded)
        val unknown = recurringHeroModel(listOf(plan.copy(homeCurrencyCode = null)), RecurringListLoadState.Loaded)
        assertNotEquals(cny, unknown)
        assertEquals(mapOf("UNKNOWN" to null), unknown.amountsByCurrency)
    }
}
