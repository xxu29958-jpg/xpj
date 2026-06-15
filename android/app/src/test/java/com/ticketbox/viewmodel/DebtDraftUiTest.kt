package com.ticketbox.viewmodel

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class DebtDraftUiTest {

    @Test
    fun parsedAmountCentsConvertsYuanAndRejectsInvalidInput() {
        // yuan → cents (2-decimal home currency), trimming whitespace.
        assertEquals(12_345L, DebtDraftUi(amountYuanInput = "123.45").parsedAmountCents())
        assertEquals(10_000L, DebtDraftUi(amountYuanInput = " 100 ").parsedAmountCents())
        // Empty / non-numeric / non-positive all reject (parsedAmountCents == null).
        assertNull(DebtDraftUi(amountYuanInput = "").parsedAmountCents())
        assertNull(DebtDraftUi(amountYuanInput = "abc").parsedAmountCents())
        assertNull(DebtDraftUi(amountYuanInput = "-5").parsedAmountCents())
        assertNull(DebtDraftUi(amountYuanInput = "0").parsedAmountCents())
    }
}
