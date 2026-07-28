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

    @Test
    fun unknownHomeRowStillMatchesSupportedOriginalLeg() {
        // PR#255 R12-B：raw-minor 只比 home 双腿，original 腿按其声明币种续配 ——
        // VND-home/USD-original 行："1200" 命中 raw home，"12.50" 命中 USD 原币腿。
        val row = searchExpense(
            amountCents = 1_200L,
            homeCurrencyCode = "VND",
        ).copy(
            originalCurrency = CurrencyCode.USD,
            originalCurrencyCode = CurrencyCode.USD,
            originalAmountMinor = 1_250L,
        )

        assertTrue(expenseMatchesSearchAmount(row, "1200"))
        assertTrue(expenseMatchesSearchAmount(row, "12.50"))
        assertFalse(expenseMatchesSearchAmount(row, "120000"))
    }

    @Test
    fun unknownOriginalRawLegMatchesByRawMinorNotHomeCoincidence() {
        // PR#255 R14-4a：CNY-home / VND-original（原码未知，枚举已回落 CNY）—— foreignOriginal
        // 判定按原码："1200" 按原 minor 命中原币腿；"12.00" 的 home 解析（1200 分）不得
        // 巧合命中 1200-VND 原 minor（旧枚举判定会把它当本币行误中）。
        val row = searchExpense(amountCents = 34L, homeCurrencyCode = "CNY").copy(
            originalCurrencyCodeRaw = "VND",
            originalAmountMinor = 1_200L,
        )

        assertTrue(expenseMatchesSearchAmount(row, "1200"))
        assertFalse(expenseMatchesSearchAmount(row, "12.00"))
    }

    @Test
    fun explicitTrailingUnknownCodeQueryMatchesRawRowsStrictly() {
        // PR#255 R14-4b："1200 VND" 粘贴直查 —— 命中 VND raw 行（原 minor 原码），
        // 严格单码：不命中 JPY/CNY 行（不借 JPY 代理外溢）；未知码拒小数（"12.5 VND" 不中）。
        val vndRow = searchExpense(amountCents = 1_200L, homeCurrencyCode = "VND")
        val jpyRow = searchExpense(amountCents = 1_200L, homeCurrencyCode = "JPY", homeCurrency = CurrencyCode.JPY)
        val cnyRow = searchExpense(amountCents = 1_200L, homeCurrencyCode = "CNY")

        assertTrue(expenseMatchesSearchAmount(vndRow, "1200 VND"))
        assertTrue(expenseMatchesSearchAmount(vndRow, "1200 vnd"))
        assertFalse(expenseMatchesSearchAmount(jpyRow, "1200 VND"))
        assertFalse(expenseMatchesSearchAmount(cnyRow, "1200 VND"))
        assertFalse(expenseMatchesSearchAmount(vndRow, "12.5 VND"))
    }

    @Test
    fun explicitKnownCodeQueryMatchesOnlyDeclaredLegs() {
        // PR#255 R14-4b 已知码："12.50 USD" → 1250 只命中 USD 腿（本行 original），
        // 不命中同值的 CNY home 腿（跨码巧合）。
        val usdOriginalRow = searchExpense(amountCents = 8_800L, homeCurrencyCode = "CNY").copy(
            originalCurrency = CurrencyCode.USD,
            originalCurrencyCode = CurrencyCode.USD,
            originalCurrencyCodeRaw = "USD",
            originalAmountMinor = 1_250L,
        )
        val cnyRow = searchExpense(amountCents = 1_250L, homeCurrencyCode = "CNY")

        assertTrue(expenseMatchesSearchAmount(usdOriginalRow, "12.50 USD"))
        assertFalse(expenseMatchesSearchAmount(cnyRow, "12.50 USD"))
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
