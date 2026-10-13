package com.ticketbox.ui.screens.expense.fact

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseFinancialSummary
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.ExpenseRelationshipImpacts
import org.junit.Assert.*
import org.junit.Test

class FactHeroTest {
    @Test fun refundsAndReversalsNeverReplaceTheOriginalSpend() {
        for (status in listOf(ExpenseLineageStatus.PartiallyRefunded, ExpenseLineageStatus.FullyRefunded, ExpenseLineageStatus.Reversed)) {
            val labels = factAmountLabels(expense(), bundleOf(status))
            assertEquals("¥268.00", labels.original)
            assertEquals("¥98.00", labels.refunded)
            assertEquals("¥170.00", labels.net)
        }
    }

    @Test fun foreignOriginalAndFrozenHomeAmountsRemainSeparate() {
        val root = expense().copy(originalAmountMinor = 1000L, originalCurrencyCodeRaw = "USD", homeCurrencyCode = "CNY")
        val bundle = bundleOf(ExpenseLineageStatus.PartiallyRefunded).let {
            it.copy(root = root, financialSummary = it.financialSummary.copy(grossOriginalMinor = 1000L, activeRefundedOriginalMinor = 200L))
        }
        val labels = factAmountLabels(root, bundle)
        assertTrue(labels.original.endsWith("10.00"))
        assertEquals("USD", labels.currencyCode)
        assertEquals("¥268.00", labels.homeGross)
        assertTrue(requireNotNull(labels.refunded).endsWith("2.00"))
        assertEquals("¥170.00", labels.net)
    }

    @Test fun unknownRefundStatusDoesNotInventZeroOrNet() {
        val labels = factAmountLabels(expense(), null)
        assertEquals("¥268.00", labels.original)
        assertNull(labels.refunded)
        assertNull(labels.net)
    }

    @Test fun unknownRecordedCurrencyRemainsVisible() {
        val labels = factAmountLabels(expense().copy(originalAmountMinor = 123L, originalCurrencyCodeRaw = "XTS"), null)
        assertEquals("XTS", labels.currencyCode)
        assertTrue(labels.original.contains("XTS"))
        assertEquals("¥268.00", labels.homeGross)
    }

    @Test fun staleOrOtherRootCannotSupplyCurrentFinancialSummary() {
        val old = bundleOf(ExpenseLineageStatus.PartiallyRefunded)
        for (root in listOf(expense().copy(rowVersion = 2L, amountCents = 30000L), expense().copy(id = 2L))) {
            val labels = factAmountLabels(root, old)
            assertNull(labels.refunded)
            assertNull(labels.net)
        }
        assertEquals("¥300.00", factAmountLabels(expense().copy(rowVersion = 2L, amountCents = 30000L), old).original)
    }

    private fun expense(): Expense = Expense(
        id = 1L,
        publicId = "fact-hero-1",
        amountCents = 26800L,
        merchant = "MUJI 无印良品",
        category = "购物",
        note = null,
        source = ExpenseSourceValues.MANUAL_ENTRY,
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = "",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "confirmed",
        expenseTime = "2026-09-02T06:15:00Z",
        createdAt = "2026-09-02T16:52:00Z",
        updatedAt = "2026-09-02T16:52:00Z",
        rowVersion = 1L,
        confirmedAt = "2026-09-02T16:52:00Z",
        rejectedAt = null,
    )

    private fun bundleOf(status: ExpenseLineageStatus): ExpenseFactBundle {
        val root = expense()
        return ExpenseFactBundle(
            root = root,
            financialSummary = ExpenseFinancialSummary(
                grossOriginalMinor = 26800L,
                grossHomeAmountCents = 26800L,
                rootStreamAmountCents = 26800L,
                activeRefundedOriginalMinor = 9800L,
                remainingRefundableOriginalMinor = 17000L,
                lineageHomeNetCents = 17000L,
                fxDifferenceCents = 0L,
                status = status,
            ),
            activeOffsets = emptyList(),
            recentHistory = emptyList(),
            relationshipImpacts = ExpenseRelationshipImpacts(
                pendingInvitesCancelled = emptyList(),
                acceptedImpacts = emptyList(),
            ),
        )
    }
}
