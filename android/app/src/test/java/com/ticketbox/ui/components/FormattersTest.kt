package com.ticketbox.ui.components

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.recordCurrencyDisplay
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import java.time.LocalDate
import java.time.ZoneOffset
import java.util.TimeZone

class FormattersTest {
    @Test
    fun parsesYuanInputToCents() {
        assertEquals(3680, parseAmountCents("36.80", CurrencyCode.CNY))
        assertEquals(3681, parseAmountCents("36.805", CurrencyCode.CNY))
        assertNull(parseAmountCents("abc", CurrencyCode.CNY))
    }

    @Test
    fun formatsCentsForTextInput() {
        assertEquals("36.80", formatAmountInput(3680, CurrencyCode.CNY))
        assertEquals("", formatAmountInput(null, CurrencyCode.CNY))
    }

    @Test
    fun parsesAndFormatsHomeInputPerCurrency() {
        // 零小数 home（JPY/KRW）：minor == major，不 ×100，且拒绝任何小数部分。
        assertEquals(1200, parseAmountCents("1200", CurrencyCode.JPY))
        assertNull(parseAmountCents("1200.5", CurrencyCode.JPY))
        assertEquals("1200", formatAmountInput(1200, CurrencyCode.JPY))
        // 2 位小数 home 保持 ×100 口径。
        assertEquals(36_805, parseAmountCents("368.05", CurrencyCode.USD))
        assertEquals("368.05", formatAmountInput(36_805, CurrencyCode.USD))
    }

    @Test
    fun rejectsFractionInputForZeroDecimalCurrencies() {
        // 严于后端 422（后端按值接受等值尾零，客户端连 "0.00" 也拒，方向安全）：
        // 零小数币种带小数部分一律 null，不再 HALF_UP 静默进位。
        assertNull(parseMinorAmount("1200.5", CurrencyCode.JPY))
        assertNull(parseMinorAmount("1200.0", CurrencyCode.JPY))
        assertNull(parseMinorAmount("0.00", CurrencyCode.KRW))
        // 整数与负 scale 记法仍可解析。
        assertEquals(1200, parseMinorAmount("1200", CurrencyCode.JPY))
        assertEquals(0, parseMinorAmount("0", CurrencyCode.KRW))
    }

    @Test
    fun parsesAndFormatsOriginalCurrencyMinorUnits() {
        assertEquals(12345, parseMinorAmount("123.45", CurrencyCode.USD))
        assertEquals(1200, parseMinorAmount("1200", CurrencyCode.JPY))
        assertNull(parseMinorAmount("-1", CurrencyCode.USD))
        assertEquals("$123.45", formatMinorAmount(12345, CurrencyCode.USD))
        assertEquals("¥1,200", formatMinorAmount(1200, CurrencyCode.JPY))
    }

    @Test
    fun sanitizesAmountInputPerCurrencyMinorUnit() {
        assertEquals("123.45", sanitizeMinorAmountInput(" ¥123.45abc ", CurrencyCode.CNY))
        assertEquals("12.34", sanitizeMinorAmountInput("12..34", CurrencyCode.USD))
        assertEquals("123", sanitizeMinorAmountInput("123.45", CurrencyCode.JPY))
        assertEquals("123456", sanitizeMinorAmountInput("123456789", CurrencyCode.CNY, maxLength = 6))
    }

    @Test
    fun formatsDisplayCurrencyAmounts() {
        assertEquals("¥123.45", formatAmount(12345, CurrencyCode.CNY))
        assertEquals("$123.45", formatAmount(12345, CurrencyCode.USD))
        // JPY / KRW 等无小数币种：amountCents 已等于 major unit，直接整数显示
        assertEquals("¥12,345", formatAmount(12345, CurrencyCode.JPY))
        assertEquals("₩12,345", formatAmount(12345, CurrencyCode.KRW))
        assertEquals("待填写金额", formatAmount(null, CurrencyCode.USD))
    }

    @Test
    fun formatsBackendHomeAmountWithBackendHomeCurrency() {
        assertEquals(
            "¥3,883.67",
            formatDisplayAmount(
                amountCents = 388367,
                display = CurrencyDisplay.Base,
            ),
        )
        assertEquals(
            "\$3,883.67",
            formatDisplayAmount(
                amountCents = 388367,
                display = CurrencyDisplay(homeCurrency = CurrencyCode.USD),
            ),
        )
        assertEquals(
            "¥3,883",
            formatDisplayAmount(
                amountCents = 3883,
                display = CurrencyDisplay(homeCurrency = CurrencyCode.JPY),
            ),
        )
    }

    @Test
    fun formatsUnknownRecordCurrencyWithRawCodeNotCnySymbol() {
        // PR#255 R7-2 / R8-4：支持集外的 record 码原样亮码 —— 原 minor 整数 + 原始码
        // （"1200 XXX"），未知 exponent 不缩放（不按 CNY 两位渲染成 "XXX12.00"）。
        // 空码仍回落 Base 同款；已知码维持既有口径。
        assertEquals(
            "1200 XXX",
            formatDisplayAmount(
                amountCents = 1200,
                display = CurrencyDisplay.forRecord("XXX"),
            ),
        )
        assertEquals(
            "¥12.00",
            formatDisplayAmount(
                amountCents = 1200,
                display = CurrencyDisplay.forRecord(null),
            ),
        )
        assertEquals(
            "¥1,200",
            formatDisplayAmount(
                amountCents = 1200,
                display = CurrencyDisplay.forRecord("jpy"),
            ),
        )
    }

    @Test
    fun formatsForeignExpenseWithOriginalPrimaryAndCnyMeta() {
        val expense = formatterExpense(
            FormatterExpenseFixture(
                amountCents = 87938,
                originalCurrencyCode = CurrencyCode.USD,
                originalAmountMinor = 12345,
                exchangeRateToCny = "7.12340000",
                exchangeRateDate = "2026-05-04",
            ),
        )

        assertEquals("$123.45", formatExpensePrimaryAmount(expense))
        assertEquals(
            "≈ ¥879.38 · 汇率 1 USD = 7.12340000 CNY · 2026-05-04",
            formatExpenseExchangeMeta(expense),
        )
    }

    @Test
    fun formatsCnyExpenseWithSelectedDisplayCurrency() {
        val expense = formatterExpense(FormatterExpenseFixture(amountCents = 3680))

        assertEquals(
            "¥36.80",
            formatExpensePrimaryAmount(
                expense = expense,
                display = CurrencyDisplay.Base,
            ),
        )
    }

    @Test
    fun hidesExchangeMetaForExpenseAlreadyInBackendHomeCurrency() {
        val expense = formatterExpense(
            FormatterExpenseFixture(
                amountCents = 12345,
                homeCurrency = CurrencyCode.JPY,
                originalCurrencyCode = CurrencyCode.JPY,
                originalAmountMinor = 12345,
                exchangeRateToCny = "1.00000000",
            ),
        )

        assertEquals(
            "¥12,345",
            formatExpensePrimaryAmount(
                expense = expense,
                display = CurrencyDisplay(homeCurrency = CurrencyCode.JPY),
            ),
        )
        assertNull(formatExpenseExchangeMeta(expense))
    }

    @Test
    fun formatsForeignExpenseWithNoFractionHomeCurrencyMeta() {
        val expense = formatterExpense(
            FormatterExpenseFixture(
                amountCents = 18518,
                homeCurrency = CurrencyCode.JPY,
                originalCurrencyCode = CurrencyCode.USD,
                originalAmountMinor = 12345,
                exchangeRateToCny = "150.00000000",
                exchangeRateDate = "2026-05-04",
            ),
        )

        assertEquals("$123.45", formatExpensePrimaryAmount(expense))
        assertEquals(
            "≈ ¥18,518 · 汇率 1 USD = 150.00000000 JPY · 2026-05-04",
            formatExpenseExchangeMeta(expense),
        )
    }

    @Test
    fun formatsForeignExpenseWithPendingFxStatus() {
        val expense = formatterExpense(
            FormatterExpenseFixture(
                amountCents = null,
                originalCurrencyCode = CurrencyCode.USD,
                originalAmountMinor = 12345,
                exchangeRateToCny = null,
                exchangeRateDate = "2026-05-04",
                fxStatus = "pending",
            ),
        )

        assertEquals("$123.45", formatExpensePrimaryAmount(expense))
        assertEquals("汇率待同步 · 2026-05-04", formatExpenseExchangeMeta(expense))
    }

    @Test
    fun primaryAmountDefaultsToRecordCurrencyDisplay() {
        // PR#255 R14-3：display 缺省改 record 口径 —— 原始 home 码未知（VND，枚举已回落
        // CNY）按 "1200 VND" 原样亮码（原 minor 整数），不再冒 env Base 的 ¥12.00；
        // 已知非 CNY record 码不 ÷100。
        val unknownHome = formatterExpense(
            FormatterExpenseFixture(amountCents = 1200, originalAmountMinor = null),
        ).copy(homeCurrencyCode = "VND")
        assertEquals("1200 VND", formatExpensePrimaryAmount(unknownHome))

        val jpyHome = formatterExpense(
            FormatterExpenseFixture(
                amountCents = 1200,
                homeCurrency = CurrencyCode.JPY,
                originalCurrencyCode = CurrencyCode.JPY,
            ),
        ).copy(homeCurrencyCode = "JPY")
        assertEquals("¥1,200", formatExpensePrimaryAmount(jpyHome))
    }

    @Test
    fun primaryAmountRendersUnknownOriginalRawCodeHonestly() {
        // PR#255 R14-3：原币腿原码未知（VND）时按原 minor 亮码，不冒回落枚举（CNY）的
        // 符号与缩放（旧口径会渲染成 "¥12.00"）。
        val expense = formatterExpense(
            FormatterExpenseFixture(amountCents = 34, originalAmountMinor = 1200),
        ).copy(homeCurrencyCode = "CNY", originalCurrencyCodeRaw = "VND")

        assertEquals("1200 VND", formatExpensePrimaryAmount(expense))
    }

    @Test
    fun recordCurrencyDisplayFallsBackToEnumWhenRawMissing() {
        // PR#255 R14-3：手工构造（raw 缺失）回落枚举口径；raw 在场优先（未知码原样亮码）。
        val manual = formatterExpense(
            FormatterExpenseFixture(amountCents = 1200, homeCurrency = CurrencyCode.JPY),
        )
        assertEquals(CurrencyDisplay(homeCurrency = CurrencyCode.JPY), manual.recordCurrencyDisplay())

        val servedUnknown = manual.copy(homeCurrencyCode = "vnd")
        assertEquals(CurrencyDisplay(unknownCode = "VND"), servedUnknown.recordCurrencyDisplay())
    }

    @Test
    fun parseForDisplayUsesRawMinorSpaceForUnknownCodes() {
        // PR#255 R15b-2：footer/均分解析 —— 未知码按原 minor 整数（"1200"→1200，不按兜底
        // 枚举放大成 120000；拒小数）；已知码维持 exponent 口径（JPY 不缩放、CNY ×100）。
        val unknown = CurrencyDisplay(unknownCode = "VND")
        assertEquals(1_200L, parseAmountCentsForDisplay("1200", unknown))
        assertNull(parseAmountCentsForDisplay("12.5", unknown))
        assertEquals(1_200L, parseAmountCentsForDisplay("1200", CurrencyDisplay(homeCurrency = CurrencyCode.JPY)))
        assertEquals(120_000L, parseAmountCentsForDisplay("1200", CurrencyDisplay.Base))
    }

    @Test
    fun displaysIsoTimeWithoutLeakingRawSeparatorInNormalCase() {
        val rendered = displayTime("2026-05-03T04:20:00Z")

        assertTrue(rendered.contains("2026-05-03"))
        assertTrue(rendered.contains(":"))
    }

    @Test
    fun displaysCompactTimeForDenseRows() {
        val previous = TimeZone.getDefault()
        TimeZone.setDefault(TimeZone.getTimeZone("Asia/Shanghai"))
        try {
            assertEquals("7/3 19:35", displayCompactTime("2026-07-03T11:35:00Z"))
        } finally {
            TimeZone.setDefault(previous)
        }
    }

    @Test
    fun updatesDateWithoutLosingExistingTime() {
        val selectedDateMillis = LocalDate.parse("2026-05-04")
            .atStartOfDay(ZoneOffset.UTC)
            .toInstant()
            .toEpochMilli()

        val iso = datePickerMillisToUtcIso(
            value = selectedDateMillis,
            currentIso = "2026-05-03T04:20:00Z",
            zoneId = ZoneOffset.UTC,
        )

        assertEquals("2026-05-04T04:20:00Z", iso)
    }

    @Test
    fun updatesTimeWithoutLosingExistingDate() {
        val iso = timePickerToUtcIso(
            hour = 8,
            minute = 45,
            currentIso = "2026-05-03T04:20:00Z",
            zoneId = ZoneOffset.UTC,
        )

        assertEquals("2026-05-03T08:45:00Z", iso)
        assertEquals(8, selectedHourFromIso(iso, ZoneOffset.UTC))
        assertEquals(45, selectedMinuteFromIso(iso, ZoneOffset.UTC))
    }

    @Test
    fun formatsStorageSize() {
        assertEquals("512 B", formatStorageSize(512))
        assertEquals("1 KB", formatStorageSize(1024))
        assertEquals("1 MB", formatStorageSize(1024 * 1024))
    }

    @Test
    fun previewDecodeSampleSizeKeepsSmallImagesAtFullResolution() {
        assertEquals(
            1,
            previewDecodeSampleSize(width = 1080, height = 2400, maxLongSide = 4096, maxPixels = 4_000_000),
        )
    }

    @Test
    fun previewDecodeSampleSizeCapsLargeImagesByLongSideAndPixels() {
        val sampleSize = previewDecodeSampleSize(width = 8000, height = 6000, maxLongSide = 2048, maxPixels = 4_000_000)

        assertEquals(4, sampleSize)
        assertTrue((8000 / sampleSize).toLong() * (6000 / sampleSize).toLong() <= 4_000_000)
        assertTrue(8000 / sampleSize <= 2048)
    }
}

private data class FormatterExpenseFixture(
    val amountCents: Long?,
    val homeCurrency: CurrencyCode = CurrencyCode.CNY,
    val originalCurrencyCode: CurrencyCode = CurrencyCode.CNY,
    val originalAmountMinor: Long? = amountCents,
    val exchangeRateToCny: String? = "1",
    val exchangeRateDate: String? = "2026-05-04",
    val fxStatus: String = "ready",
)

private fun formatterExpense(fixture: FormatterExpenseFixture): Expense = Expense(
    id = 1,
    publicId = "formatter-expense",
    amountCents = fixture.amountCents,
    homeAmountCents = fixture.amountCents,
    homeCurrency = fixture.homeCurrency,
    originalCurrency = fixture.originalCurrencyCode,
    originalAmount = null,
    fxRate = fixture.exchangeRateToCny,
    fxRateDate = fixture.exchangeRateDate,
    fxSource = "manual",
    fxStatus = fixture.fxStatus,
    originalCurrencyCode = fixture.originalCurrencyCode,
    originalAmountMinor = fixture.originalAmountMinor,
    exchangeRateToCny = fixture.exchangeRateToCny,
    exchangeRateDate = fixture.exchangeRateDate,
    exchangeRateSource = "manual",
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
