package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * [filterConfirmedStreamItems] mirrors the server-owned stream filter semantics
 * over the synced cache: month = the row's server stream_date, category = the
 * row's own snapshot (offset category for events, root category for bills),
 * tag = root tags on both kinds. No amount/FX recomputation anywhere.
 */
class ConfirmedStreamItemFilterTest {
    private val root = expense(id = 1, merchant = "夏日酒店", category = "旅游", tags = "旅行, 团建")

    @Test
    fun monthMatchesEachRowsOwnStreamDate() {
        val augustBill = expenseRow(root, streamDate = "2026-08-15")
        val septemberRefund = offsetRow(
            root,
            streamDate = "2026-09-03",
            category = "旅游",
        )

        val september = filterConfirmedStreamItems(
            items = listOf(augustBill, septemberRefund),
            criteria = ExpenseFilterCriteria(month = "2026-09"),
        )

        assertEquals(listOf(septemberRefund), september)
    }

    @Test
    fun categoryMatchesTheOffsetsOwnSnapshotNotTheRoot() {
        val bill = expenseRow(root, streamDate = "2026-08-15")
        val refund = offsetRow(root, streamDate = "2026-09-03", category = "购物")

        val shopping = filterConfirmedStreamItems(
            items = listOf(bill, refund),
            criteria = ExpenseFilterCriteria(category = "购物"),
        )
        val travel = filterConfirmedStreamItems(
            items = listOf(bill, refund),
            criteria = ExpenseFilterCriteria(category = "旅游"),
        )

        assertEquals(listOf(refund), shopping)
        assertEquals(listOf(bill), travel)
    }

    @Test
    fun tagInheritsRootTagsForBothKinds() {
        val bill = expenseRow(root, streamDate = "2026-08-15")
        val reversal = offsetRow(root, streamDate = "2026-09-04", kind = StreamOffsetKind.Reversal)

        val tagged = filterConfirmedStreamItems(
            items = listOf(bill, reversal),
            criteria = ExpenseFilterCriteria(tag = "旅行"),
        )

        assertEquals(listOf(bill, reversal), tagged)
    }

    @Test
    fun queryMatchesRootMerchantAndOffsetCategory() {
        val bill = expenseRow(root, streamDate = "2026-08-15")
        val refund = offsetRow(root, streamDate = "2026-09-03", category = "购物")

        val byMerchant = filterConfirmedStreamItems(
            items = listOf(bill, refund),
            criteria = ExpenseFilterCriteria(query = "酒店"),
        )
        val byOffsetCategory = filterConfirmedStreamItems(
            items = listOf(bill, refund),
            criteria = ExpenseFilterCriteria(query = "购物"),
        )

        // Offset rows are reachable through the root bill's merchant.
        assertEquals(listOf(bill, refund), byMerchant)
        assertEquals(listOf(refund), byOffsetCategory)
    }

    @Test
    fun blankCriteriaKeepsServerOrderUntouched() {
        val bill = expenseRow(root, streamDate = "2026-08-15")
        val refund = offsetRow(root, streamDate = "2026-09-03")

        val all = filterConfirmedStreamItems(
            items = listOf(refund, bill),
            criteria = ExpenseFilterCriteria(),
        )

        assertEquals(listOf(refund, bill), all)
    }

    private fun expenseRow(
        root: Expense,
        streamDate: String,
    ): ConfirmedStreamItem.ExpenseRow = ConfirmedStreamItem.ExpenseRow(
        streamDate = streamDate,
        streamAmountCents = root.amountCents ?: 0L,
        root = root,
        lineageStatus = ExpenseLineageStatus.Confirmed,
        lineageHomeNetCents = root.amountCents ?: 0L,
    )

    private fun offsetRow(
        root: Expense,
        streamDate: String,
        kind: StreamOffsetKind = StreamOffsetKind.Refund,
        category: String = "旅游",
    ): ConfirmedStreamItem.OffsetRow = ConfirmedStreamItem.OffsetRow(
        streamDate = streamDate,
        streamAmountCents = if (kind.isMoneyEvent) -(root.amountCents ?: 0L) else 0L,
        root = root,
        lineageStatus = ExpenseLineageStatus.PartiallyRefunded,
        lineageHomeNetCents = 0L,
        offset = StreamOffset(
            publicId = "off-${kind.name}-$streamDate",
            kind = kind,
            amountCents = root.amountCents ?: 0L,
            originalAmountMinor = root.amountCents ?: 0L,
            originalCurrencyCode = "CNY",
            homeCurrencyCode = "CNY",
            category = category,
        ),
    )

    private fun expense(id: Long, merchant: String, category: String, tags: String?): Expense = Expense(
        id = id,
        publicId = "exp-$id",
        amountCents = 1200,
        merchant = merchant,
        category = category,
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
        tags = tags,
        valueScore = null,
        regretScore = null,
        status = "confirmed",
        expenseTime = "2026-08-15T04:00:00Z",
        createdAt = "2026-08-15T04:00:00Z",
        updatedAt = "2026-08-15T04:00:00Z",
        rowVersion = 1L,
        confirmedAt = "2026-08-15T04:01:00Z",
        rejectedAt = null,
    )
}
