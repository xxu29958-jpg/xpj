package com.ticketbox.ui.screens.expense.fact

import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.ExpenseOffsetStatus
import com.ticketbox.domain.model.StreamOffsetKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class FactOffsetAmountPresentationTest {
    @Test
    fun refundAndChargebackExposeInflowAmount() {
        assertEquals("+¥3.00", offsetInflowAmountText(offset(StreamOffsetKind.Refund)))
        assertEquals("+¥3.00", offsetInflowAmountText(offset(StreamOffsetKind.Chargeback)))
    }

    @Test
    fun reversalDoesNotPresentTheRootGrossAsAnInflow() {
        assertNull(offsetInflowAmountText(offset(StreamOffsetKind.Reversal)))
    }
}

private fun offset(kind: StreamOffsetKind) = ExpenseOffsetFact(
    publicId = "offset-1",
    kind = kind,
    status = ExpenseOffsetStatus.Active,
    originalCurrencyCode = "CNY",
    originalAmountMinor = 300,
    homeCurrencyCode = "CNY",
    amountCents = 300,
    streamAmountCents = -300,
    accountingDate = "2026-09-03",
    category = "餐饮",
    reason = "用户说明",
    rowVersion = 1,
    factRevision = 1,
    createdAt = "2026-09-03T04:00:00Z",
    updatedAt = "2026-09-03T04:00:00Z",
)
