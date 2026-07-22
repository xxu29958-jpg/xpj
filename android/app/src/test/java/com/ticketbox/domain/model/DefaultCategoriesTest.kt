package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DefaultCategoriesTest {
    @Test
    fun normalizesLegacyFoodCategory() {
        assertEquals("餐饮", normalizeExpenseCategory("吃饭"))
        assertEquals("餐饮", normalizeExpenseCategory("  餐饮  "))
        assertEquals("其他", normalizeExpenseCategory(" "))
    }

    @Test
    fun recognizesUncategorizedTransportValues() {
        assertTrue(isUncategorizedExpenseCategory(""))
        assertTrue(isUncategorizedExpenseCategory(" 未分类 "))
        assertTrue(isUncategorizedExpenseCategory("未分類"))
        assertTrue(isUncategorizedExpenseCategory("NONE"))
        assertFalse(isUncategorizedExpenseCategory("其他"))
        assertFalse(isUncategorizedExpenseCategory("餐饮"))
    }

    @Test
    fun uncategorizedTokenSharedSamples() {
        // Shared with backend tests/test_data_quality_caliber_port.py — the
        // data-quality counters port this exact rule; any drift must redden
        // one of the two twins.
        listOf(
            null,
            "",
            "  ",
            "未分类",
            " 未分类 ",
            "未分類",
            "none",
            "None",
            "NONE",
            "nOnE",
            "null",
            "NULL",
            "Null",
            " none ",
            "\tnull\t",
        ).forEach { category ->
            assertTrue(isUncategorizedExpenseCategory(category), "must be uncategorized: $category")
        }
        listOf("其他", "餐饮", "nonee", "nullable", "未分类x").forEach { category ->
            assertFalse(isUncategorizedExpenseCategory(category), "must be categorized: $category")
        }
    }

    @Test
    fun mergesRemoteCategoriesBehindStableDefaults() {
        val merged = mergeExpenseCategories(listOf("吃饭", "宠物", "交通"))

        assertEquals("餐饮", merged.first())
        assertTrue("宠物" in merged)
        assertTrue("AI订阅" in merged)
        assertFalse("吃饭" in merged)
    }
}
