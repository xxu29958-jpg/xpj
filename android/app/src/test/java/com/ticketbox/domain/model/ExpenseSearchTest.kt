package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ExpenseSearchTest {

    @Test
    fun unknownHomeCurrencyRowMatchesByRawMinorValue() {
        // PR#255 R10⑥：home 码在支持集外（新版服务端币种，显示口径 "1200 VND"，R8-4）——
        // 金额匹配按原 minor 整数值："1200" 必须命中 1200，而非按 CNY 解析成 120000。
        val row = searchExpense(amountCents = 1_200L, homeCurrencyCode = "VND")

        assertTrue(expenseMatchesSearchAmount(row, "1200"))
        assertFalse(expenseMatchesSearchAmount(row, "120000"))
        assertFalse(expenseMatchesSearchAmount(row, "12.00"))
    }

    @Test
    fun blankRawCodeKeepsEnumPathSemantics() {
        // 回归：raw 缺失（旧 record / 手工构造）不落原值分支 —— CNY 行 "12" 仍按分口径命中。
        val row = searchExpense(amountCents = 1_200L, homeCurrencyCode = null)

        assertTrue(expenseMatchesSearchAmount(row, "12"))
        assertFalse(expenseMatchesSearchAmount(row, "1200"))
    }

    @Test
    fun knownHomeCurrencyRowMatchingUnchanged() {
        // 已知码路径不动：JPY 行按零小数 home 命中；CNY 行按分命中。
        val jpyRow = searchExpense(amountCents = 1_200L, homeCurrencyCode = "JPY", homeCurrency = CurrencyCode.JPY)
        val cnyRow = searchExpense(amountCents = 1_200L, homeCurrencyCode = "CNY")

        assertTrue(expenseMatchesSearchAmount(jpyRow, "1200"))
        assertFalse(expenseMatchesSearchAmount(jpyRow, "120000"))
        assertTrue(expenseMatchesSearchAmount(cnyRow, "12"))
        assertFalse(expenseMatchesSearchAmount(cnyRow, "1200"))
    }
}

private fun searchExpense(
    amountCents: Long,
    homeCurrencyCode: String?,
    homeCurrency: CurrencyCode = CurrencyCode.CNY,
): Expense = Expense(
    id = 1,
    publicId = "search-expense",
    amountCents = amountCents,
    homeAmountCents = amountCents,
    homeCurrency = homeCurrency,
    homeCurrencyCode = homeCurrencyCode,
    originalAmountMinor = amountCents,
    merchant = "merchant",
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
    expenseTime = "2026-05-04T00:00:00Z",
    createdAt = "2026-05-04T00:00:00Z",
    updatedAt = "2026-05-04T00:00:00Z",
    rowVersion = 1L,
    confirmedAt = "2026-05-04T00:00:00Z",
    rejectedAt = null,
)
