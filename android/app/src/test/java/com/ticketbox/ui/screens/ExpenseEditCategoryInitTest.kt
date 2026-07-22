package com.ticketbox.ui.screens

import com.ticketbox.domain.model.Expense
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * Edit-form category init must read the server-stored truth (PR #230 round
 * 12): display-normalized 「其他」 must not masquerade as a real category for
 * rows whose raw category is blank / a dirty token.
 */
class ExpenseEditCategoryInitTest {
    @Test
    fun rawBlankAndDirtyTokensInitializeEmpty() {
        assertEquals("", editInitialCategory(expense(serverCategory = "", category = "其他")))
        assertEquals("", editInitialCategory(expense(serverCategory = "none", category = "none")))
        assertEquals("", editInitialCategory(expense(serverCategory = "未分類", category = "未分類")))
        assertEquals("", editInitialCategory(expense(serverCategory = "  ", category = "其他")))
    }

    @Test
    fun fallbackWhenNoRawValueAndValidRawKeepsDisplayValue() {
        // No raw value (legacy/manual constructions): the display value is the
        // only truth — uncategorized display still means empty.
        assertEquals("", editInitialCategory(expense(serverCategory = null, category = "未分类")))
        assertEquals("餐饮", editInitialCategory(expense(serverCategory = null, category = "餐饮")))
        // Valid raw initializes to the display (alias-normalized) category.
        assertEquals("餐饮", editInitialCategory(expense(serverCategory = "餐饮", category = "餐饮")))
        assertEquals("餐饮", editInitialCategory(expense(serverCategory = "吃饭", category = "餐饮")))
    }

    private fun expense(serverCategory: String?, category: String): Expense = Expense(
        id = 1L,
        publicId = "edit-cat-1",
        amountCents = 1200L,
        merchant = "星巴克",
        serverCategory = serverCategory,
        category = category,
        note = null,
        source = "android-qa",
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
        expenseTime = "2026-05-12T10:15:00Z",
        createdAt = "2026-05-12T10:15:00Z",
        updatedAt = "2026-05-12T10:15:00Z",
        rowVersion = 1L,
        confirmedAt = "2026-05-12T10:15:00Z",
        rejectedAt = null,
    )
}
