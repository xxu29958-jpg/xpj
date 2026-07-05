package com.ticketbox.ui.screens

import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.viewmodel.BillSplitSentLoadState
import com.ticketbox.viewmodel.ExpenseEditUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

internal class BillSplitRemainingCentsTest {
    @Test
    fun remainingHiddenUntilSentListLoaded() {
        val base = state(loadState = BillSplitSentLoadState.Unknown)

        assertNull(billSplitRemainingCents(base))
        assertNull(billSplitRemainingCents(base.copy(billSplitSentLoadState = BillSplitSentLoadState.Loading)))
        assertNull(billSplitRemainingCents(base.copy(billSplitSentLoadState = BillSplitSentLoadState.Failed)))
    }

    @Test
    fun loadedEmptySentListShowsParentAmount() {
        val state = state(loadState = BillSplitSentLoadState.Loaded)

        assertEquals(1_000L, billSplitRemainingCents(state))
    }

    @Test
    fun loadedSentListSubtractsOnlyActiveInvitations() {
        val state = state(
            loadState = BillSplitSentLoadState.Loaded,
            sent = listOf(
                sent("active-invited", BillSplitStatusValues.INVITED, 250L),
                sent("active-accepted", BillSplitStatusValues.ACCEPTED, 300L),
                sent("rejected", BillSplitStatusValues.REJECTED, 900L),
                sent("cancelled", BillSplitStatusValues.CANCELLED, 900L),
            ),
        )

        assertEquals(450L, billSplitRemainingCents(state))
    }

    private fun state(
        loadState: BillSplitSentLoadState,
        sent: List<BillSplitSent> = emptyList(),
    ): ExpenseEditUiState = ExpenseEditUiState(
        expense = expense(),
        billSplitSentLoadState = loadState,
        billSplitSent = sent,
    )

    private fun expense(): Expense = Expense(
        id = 7L,
        publicId = "expense-7",
        amountCents = 1_000L,
        originalCurrency = CurrencyCode.CNY,
        originalCurrencyCode = CurrencyCode.CNY,
        originalAmountMinor = 1_000L,
        merchant = "Merchant",
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
        status = "confirmed",
        expenseTime = null,
        createdAt = "2026-01-01T00:00:00Z",
        updatedAt = "2026-01-01T00:00:00Z",
        rowVersion = 1L,
        confirmedAt = "2026-01-01T00:00:00Z",
        rejectedAt = null,
    )

    private fun sent(publicId: String, status: String, amountCents: Long): BillSplitSent = BillSplitSent(
        publicId = publicId,
        status = status,
        amountCents = amountCents,
        merchantSnapshot = null,
        categorySuggestion = null,
        expenseTimeSnapshot = null,
        expiresAt = "2026-02-01T00:00:00Z",
        createdAt = "2026-01-01T00:00:00Z",
        acceptedAt = null,
        rejectedAt = null,
        cancelledAt = null,
        expiredAt = null,
        receiverAccountId = 2L,
        receiverDisplayNameSnapshot = "家人",
        senderExpenseId = 7L,
    )
}
