package com.ticketbox.ui.screens.pending.sheets

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class QuickMerchantSheetTest {
    @Test
    fun noiseTextDisablesSave() {
        // 与 NeedsMerchant 判定同型（PR #230 round 9）：噪音文本不允许"修好"一张票。
        listOf("12:34", "A", "123456", "2026-07-17 12:34", "——", "  ", "").forEach { value ->
            assertFalse(quickMerchantSaveEnabled(value), "must disable save: $value")
        }
    }

    @Test
    fun usableMerchantEnablesSave() {
        listOf("星巴克", "3M", "A1", "7-Eleven").forEach { value ->
            assertTrue(quickMerchantSaveEnabled(value), "must enable save: $value")
        }
    }
}
