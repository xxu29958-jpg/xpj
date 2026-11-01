package com.ticketbox.data.repository

import com.ticketbox.domain.model.CurrencyCode
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class ExpenseFundingInputTest {
    private val selected = ExpenseFundingInput("component", "account", 3, "厦门", "CNY", "CNY")

    @Test fun `one existing CNY account uses the authoritative expense total`() {
        val funding = readExpenseFunding(fundingInputAdapter.toJson(listOf(selected)), CurrencyCode.CNY, 2933).single()
        assertEquals(2933L, funding.expenseAmountMinor)
        assertEquals(2933L, funding.accountAmountMinor)
        assertEquals("account", funding.accountPublicId)
        assertEquals(3L, funding.accountRowVersion)
    }

    @Test fun `split foreign and malformed amounts still require explicit valid input`() {
        for (rows in listOf(listOf(selected, selected.copy(componentId = "other")),
            listOf(selected.copy(accountCurrency = "USD")), listOf(selected.copy(expenseAmount = "bad")))) {
            assertFailsWith<IllegalArgumentException> {
                readExpenseFunding(fundingInputAdapter.toJson(rows), CurrencyCode.CNY, 2933)
            }
        }
    }
}
