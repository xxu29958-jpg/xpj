package com.ticketbox.ui.screens.pending.sheets

import kotlin.test.Test
import kotlin.test.assertEquals

class QuickCategorySheetTest {
    @Test
    fun dirtyTokensPrefillEmptySoSavingRequiresAnActiveChoice() {
        // Otherwise the sheet preselects the invalid token and an unchanged
        // save re-persists it (PR #230 round 7).
        listOf("未分类", "未分類", "none", "None", "null", "NULL", " none ").forEach { token ->
            assertEquals("", quickCategoryInitialSelection(token, token), "token must prefill empty: $token")
        }
    }

    @Test
    fun realCategoriesKeepTheirPrefill() {
        assertEquals("餐饮", quickCategoryInitialSelection("餐饮", "餐饮"))
        assertEquals("其他", quickCategoryInitialSelection("其他", "其他"))
        assertEquals("", quickCategoryInitialSelection("", ""))
        assertEquals("", quickCategoryInitialSelection("  ", "  "))
    }

    @Test
    fun rawBlankNormalizedToOtherAlsoRequiresAnActiveChoice() {
        // Raw blank categories are displayed as 其他; seeding the sheet from
        // that normalized display value would let an unchanged save write 其他
        // and clear the data-quality issue without a real choice (PR #230 round 10).
        assertEquals("", quickCategoryInitialSelection("", "其他"))
        assertEquals("", quickCategoryInitialSelection("  ", "其他"))
        // Non-fresh rows without a raw value keep the display-based behaviour.
        assertEquals("其他", quickCategoryInitialSelection(null, "其他"))
        assertEquals("餐饮", quickCategoryInitialSelection(null, "餐饮"))
    }
}
