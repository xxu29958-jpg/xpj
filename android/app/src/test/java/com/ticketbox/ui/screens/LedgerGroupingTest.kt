package com.ticketbox.ui.screens

import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.StreamOffset
import com.ticketbox.domain.model.StreamOffsetKind
import com.ticketbox.ui.screens.ledger.shouldCompactLedgerDayGroups
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Pure-JVM coverage for the confirmed-stream day-group subtotal. The subtotal
 * sums ONLY the server-owned [ConfirmedStreamItem.streamAmountCents]:
 * refund/chargeback contribute negative amounts, a reversal event and its
 * reversed root both contribute 0 — gross `amountCents` must never leak back
 * into the day total. Grouping/label resolution needs Android Resources and is
 * exercised by instrumented tests; this pins the arithmetic and keying.
 */
class LedgerGroupingTest {
    @Test
    fun dayTotalSumsServerStreamContributions() {
        val group = LedgerStreamGroup(
            key = "2026-05-17",
            label = "5月17日 六",
            items = listOf(
                expenseRow(id = 1, streamAmountCents = 1200),
                expenseRow(id = 2, streamAmountCents = 3000),
                expenseRow(id = 3, streamAmountCents = 450),
            ),
        )

        assertEquals(4650L, group.dayTotalCents)
    }

    @Test
    fun dayTotalAddsRefundAndChargebackAsNegativeContributions() {
        val group = LedgerStreamGroup(
            key = "2026-05-17",
            label = "5月17日 六",
            items = listOf(
                expenseRow(id = 1, amountCents = 12_000, streamAmountCents = 12_000),
                offsetRow(
                    publicId = "off-r",
                    kind = StreamOffsetKind.Refund,
                    amountCents = 3000,
                    streamAmountCents = -3000,
                ),
                offsetRow(
                    publicId = "off-c",
                    kind = StreamOffsetKind.Chargeback,
                    amountCents = 1000,
                    streamAmountCents = -1000,
                ),
            ),
        )

        // 120.00 - 30.00 - 10.00: the gross root amount (12_000) plus the two
        // negative server contributions — never a recomputed net of amounts.
        assertEquals(8000L, group.dayTotalCents)
    }

    @Test
    fun reversalEventAndReversedRootContributeZero() {
        val group = LedgerStreamGroup(
            key = "2026-05-18",
            label = "5月18日 日",
            items = listOf(
                expenseRow(
                    id = 2,
                    amountCents = 8000,
                    streamAmountCents = 0,
                    lineageStatus = ExpenseLineageStatus.Reversed,
                    lineageHomeNetCents = 0,
                ),
                offsetRow(
                    publicId = "off-x",
                    kind = StreamOffsetKind.Reversal,
                    amountCents = 8000,
                    streamAmountCents = 0,
                ),
            ),
        )

        assertEquals(0L, group.dayTotalCents)
        assertEquals(2, group.itemCount)
    }

    @Test
    fun rowKeysKeepOffsetsDisjointFromRoots() {
        val root = expenseRow(id = 7)
        val offset = offsetRow(
            publicId = "off-7",
            kind = StreamOffsetKind.Refund,
            amountCents = 100,
            streamAmountCents = -100,
            root = LedgerRootFixture(id = 7),
        )

        assertEquals("expense-7", root.rowKey)
        assertEquals("offset-off-7", offset.rowKey)
        assertTrue(root.rowKey != offset.rowKey)
    }

    @Test
    fun compactDayGroupsOnlyStartsForLongLedgerLists() {
        assertFalse(shouldCompactLedgerDayGroups(groupCount = 1, itemCount = 8))
        assertFalse(shouldCompactLedgerDayGroups(groupCount = 2, itemCount = 8))
        assertTrue(shouldCompactLedgerDayGroups(groupCount = 2, itemCount = 9))
        assertTrue(shouldCompactLedgerDayGroups(groupCount = 1, itemCount = 13))
    }

    @Test
    fun dayPreviewLabelsPrioritizeLargeAmounts() {
        val labels = ledgerDayPreviewLabels(
            items = listOf(
                expenseRow(id = 1, amountCents = 900).withRoot { it.copy(merchant = "Coffee") },
                expenseRow(id = 2, amountCents = 30_000).withRoot { it.copy(merchant = "Rent") },
                expenseRow(id = 3, amountCents = 5_000).withRoot { it.copy(merchant = "Market") },
                expenseRow(id = 4, amountCents = 12_000).withRoot { it.copy(merchant = "Pharmacy") },
            ),
            limit = 3,
        )

        assertEquals(listOf("Rent", "Pharmacy", "Market"), labels)
    }

    @Test
    fun dayPreviewLabelsDeduplicateMerchantByLargestAmount() {
        val labels = ledgerDayPreviewLabels(
            items = listOf(
                expenseRow(id = 1, amountCents = 900).withRoot { it.copy(merchant = "Coffee") },
                expenseRow(id = 2, amountCents = 12_000).withRoot { it.copy(merchant = "Coffee") },
                expenseRow(id = 3, amountCents = 5_000).withRoot { it.copy(merchant = "Market") },
            ),
            limit = 3,
        )

        assertEquals(listOf("Coffee", "Market"), labels)
    }

    @Test
    fun offsetRowPreviewUsesRootMerchantWithOffsetMagnitude() {
        val labels = ledgerDayPreviewLabels(
            items = listOf(
                expenseRow(id = 1, amountCents = 900).withRoot { it.copy(merchant = "Coffee") },
                offsetRow(
                    publicId = "off-big",
                    kind = StreamOffsetKind.Refund,
                    amountCents = 20_000,
                    streamAmountCents = -20_000,
                    root = LedgerRootFixture(merchant = "Hotel"),
                ),
            ),
            limit = 2,
        )

        // The refund event surfaces by its root merchant, weighted by its own
        // magnitude — a large refund is as salient as a large bill.
        assertEquals(listOf("Hotel", "Coffee"), labels)
    }
}

private fun ConfirmedStreamItem.ExpenseRow.withRoot(edit: (Expense) -> Expense) = copy(root = edit(root))

private fun expenseRow(
    id: Long,
    amountCents: Long? = 1200,
    streamAmountCents: Long = amountCents ?: 0L,
    lineageStatus: ExpenseLineageStatus = ExpenseLineageStatus.Confirmed,
    lineageHomeNetCents: Long = streamAmountCents,
): ConfirmedStreamItem.ExpenseRow = ConfirmedStreamItem.ExpenseRow(
    streamDate = "2026-05-17",
    streamAmountCents = streamAmountCents,
    root = expense(id = id, amountCents = amountCents),
    lineageStatus = lineageStatus,
    lineageHomeNetCents = lineageHomeNetCents,
)

private data class LedgerRootFixture(
    val id: Long = 99,
    val merchant: String = "商家99",
)

private fun offsetRow(
    publicId: String,
    kind: StreamOffsetKind,
    amountCents: Long,
    streamAmountCents: Long,
    root: LedgerRootFixture = LedgerRootFixture(),
): ConfirmedStreamItem.OffsetRow = ConfirmedStreamItem.OffsetRow(
    streamDate = "2026-05-17",
    streamAmountCents = streamAmountCents,
    root = expense(id = root.id, amountCents = amountCents).copy(merchant = root.merchant),
    lineageStatus = ExpenseLineageStatus.PartiallyRefunded,
    lineageHomeNetCents = 0L,
    offset = StreamOffset(
        publicId = publicId,
        kind = kind,
        amountCents = amountCents,
        originalAmountMinor = amountCents,
        originalCurrencyCode = "CNY",
        homeCurrencyCode = "CNY",
        category = "餐饮",
    ),
)

private fun expense(id: Long, amountCents: Long?): Expense = Expense(
    id = id,
    publicId = "exp-$id",
    amountCents = amountCents,
    merchant = "商家$id",
    category = "餐饮",
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
    expenseTime = "2026-05-17T08:00:00Z",
    createdAt = "2026-05-17T08:00:00Z",
    updatedAt = "2026-05-17T08:00:00Z",
    rowVersion = 1L,
    confirmedAt = "2026-05-17T08:01:00Z",
    rejectedAt = null,
)
