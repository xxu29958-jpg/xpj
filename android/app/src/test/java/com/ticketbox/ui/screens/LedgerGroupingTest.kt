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

        assertEquals(mapOf<String?, Long?>("CNY" to 4650L), group.amountsByCurrency)
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
        assertEquals(mapOf<String?, Long?>("CNY" to 8000L), group.amountsByCurrency)
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

        assertEquals(mapOf<String?, Long?>("CNY" to 0L), group.amountsByCurrency)
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
    fun dayPreviewLabelsPreserveServerOrderAcrossDifferentCurrencies() {
        val labels = ledgerDayPreviewLabels(
            items = listOf(
                expenseRow(id = 1, amountCents = 900).withRoot { it.copy(merchant = "Coffee") },
                expenseRow(id = 2, amountCents = 30_000).withRoot { it.copy(merchant = "Rent", homeCurrencyCode = "JPY") },
                expenseRow(id = 3, amountCents = 5_000).withRoot { it.copy(merchant = "Market") },
                expenseRow(id = 4, amountCents = 12_000).withRoot { it.copy(merchant = "Pharmacy") },
            ),
            limit = 3,
        )

        assertEquals(listOf("Coffee", "Rent", "Market"), labels)
    }

    @Test
    fun dayPreviewLabelsDeduplicateInEncounterOrder() {
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
    fun offsetRowPreviewUsesRootMerchantInOriginalPosition() {
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

        assertEquals(listOf("Coffee", "Hotel"), labels)
    }

    @Test
    fun groupAndPageSummariesKeepEachRowsOwnCurrency() {
        val refund = offsetRow("jpy-refund", StreamOffsetKind.Refund, 50, -50)
        val items = listOf(
            expenseRow(1, amountCents = 100),
            expenseRow(2, amountCents = 100).withRoot { it.copy(homeCurrencyCode = "JPY") },
            refund.copy(offset = refund.offset.copy(homeCurrencyCode = "JPY")),
        )
        val expected = mapOf<String?, Long?>("CNY" to 100L, "JPY" to 50L)
        assertEquals(expected, LedgerStreamGroup("2026-05-17", "date", items).amountsByCurrency)
        assertEquals(expected, com.ticketbox.viewmodel.LedgerUiState(items = items).summary.amountsByCurrency)
    }

    @Test
    fun missingCurrencyAndMissingAmountNeverBecomeYuanOrZero() {
        val items = listOf(
            expenseRow(1, amountCents = 100).withRoot { it.copy(homeCurrencyCode = null) },
            expenseRow(2, amountCents = 100).withRoot { it.copy(homeCurrencyCode = "  ") },
            expenseRow(3, amountCents = null),
            expenseRow(4, amountCents = 100),
        )
        assertEquals(mapOf<String?, Long?>(null to null, "CNY" to null), LedgerStreamGroup("date", "date", items).amountsByCurrency)
    }

    @Test
    fun declaredUnknownCodeRemainsRawAndOverflowRemainsUnavailable() {
        val items = listOf(
            expenseRow(1, amountCents = 100).withRoot { it.copy(homeCurrencyCode = "ZZZ") },
            expenseRow(2, amountCents = 50).withRoot { it.copy(homeCurrencyCode = " zzz ") },
            expenseRow(3, amountCents = Long.MAX_VALUE),
            expenseRow(4, amountCents = 1),
        )
        assertEquals(mapOf<String?, Long?>("ZZZ" to 150L, "CNY" to null), LedgerStreamGroup("date", "date", items).amountsByCurrency)
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
    homeCurrencyCode = "CNY",
)
