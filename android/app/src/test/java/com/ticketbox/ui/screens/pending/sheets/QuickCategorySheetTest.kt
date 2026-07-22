package com.ticketbox.ui.screens.pending.sheets

import kotlin.test.Test
import kotlin.test.assertEquals

class QuickCategorySheetTest {
    @Test
    fun dirtyTokensPrefillEmptySoSavingRequiresAnActiveChoice() {
        // Otherwise the sheet preselects the invalid token and an unchanged
        // save re-persists it (PR #230 round 7).
        listOf("未分类", "未分類", "none", "None", "null", "NULL", " none ").forEach { token ->
            assertEquals("", quickCategoryInitialSelection(token), "token must prefill empty: $token")
        }
    }

    @Test
    fun realCategoriesKeepTheirPrefill() {
        assertEquals("餐饮", quickCategoryInitialSelection("餐饮"))
        assertEquals("其他", quickCategoryInitialSelection("其他"))
        assertEquals("", quickCategoryInitialSelection(""))
        assertEquals("", quickCategoryInitialSelection("  "))
    }
}
