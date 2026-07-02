package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import kotlin.test.Test
import kotlin.test.assertEquals

internal class ExpenseEditAmountInputTest {

    @Test
    fun initialAmountUsesExpenseFieldsInsteadOfSampleValues() {
        val parsedOriginal = expense(amountCents = 3_680L, originalAmountMinor = 1_730L)
        val homeOnly = expense(amountCents = 3_680L, originalAmountMinor = null)

        assertEquals(1_730L, initialExpenseAmountInputMinor(parsedOriginal))
        assertEquals(3_680L, initialExpenseAmountInputMinor(homeOnly))
    }
}

private fun expense(
    amountCents: Long?,
    originalAmountMinor: Long?,
): Expense = Expense(
    id = 1L,
    publicId = "expense-1",
    amountCents = amountCents,
    originalCurrency = CurrencyCode.CNY,
    originalCurrencyCode = CurrencyCode.CNY,
    originalAmountMinor = originalAmountMinor,
    merchant = "商家",
    category = "其他",
    note = null,
    source = "manual",
    imagePath = null,
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    confidence = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = null,
    valueScore = null,
    regretScore = null,
    status = "pending",
    expenseTime = null,
    createdAt = "2026-07-01T00:00:00Z",
    updatedAt = "2026-07-01T00:00:00Z",
    rowVersion = 1L,
    confirmedAt = null,
    rejectedAt = null,
)
