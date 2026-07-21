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
    fun mergesRemoteCategoriesBehindStableDefaults() {
        val merged = mergeExpenseCategories(listOf("吃饭", "宠物", "交通"))

        assertEquals("餐饮", merged.first())
        assertTrue("宠物" in merged)
        assertTrue("AI订阅" in merged)
        assertFalse("吃饭" in merged)
    }
}
