package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.CategoryStatsDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseSplitDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.TagStatsDto
import com.ticketbox.domain.model.CategoryStats
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.TagStats
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class ExpenseMappersTest {
    @Test
    fun mapsPublicIdFromServer() {
        val expense = expenseDto(publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2").toDomain()

        assertEquals("691da31d-e8d7-49b0-bece-ec6f61c044b2", expense.publicId)
    }

    @Test
    fun failsWithReadableMessageWhenServerOmitsPublicId() {
        val error = assertFailsWith<RepositoryException> {
            expenseDto(publicId = null).toDomain()
        }

        assertEquals("账本版本过旧，请重启电脑上的小票夹后再试。", error.message)
    }

    @Test
    fun normalizesLegacyCategoryFromServer() {
        val expense = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            category = "吃饭",
        ).toDomain()

        assertEquals("餐饮", expense.category)
    }

    @Test
    fun mapsForeignCurrencyFieldsFromServerAndDraftRequests() {
        val expense = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            originalCurrencyCode = "USD",
            originalAmountMinor = 12345,
            fxRate = "7.12340000",
            fxRateDate = "2026-05-04",
            fxStatus = "ready",
        ).toDomain()

        assertEquals(CurrencyCode.USD, expense.originalCurrencyCode)
        assertEquals(12345, expense.originalAmountMinor)
        assertEquals("7.12340000", expense.exchangeRateToCny)
        assertEquals("7.12340000", expense.fxRate)
        assertEquals("2026-05-04", expense.exchangeRateDate)

        val request = ExpenseDraft(
            amountCents = null,
            originalCurrencyCode = CurrencyCode.JPY,
            originalAmountMinor = 1200,
            merchant = "东京交通",
            category = "交通",
            note = null,
            expenseTime = "2026-05-04T04:00:00Z",
            tags = null,
            valueScore = null,
            regretScore = null,
        ).toRequest()

        assertEquals("JPY", request.originalCurrency)
        assertEquals("1200", request.originalAmount)
        assertEquals("2026-05-04T04:00:00Z", request.spentAt)
    }

    @Test
    fun mapsLegacyFxAliasesWhenCanonicalFieldsAreMissing() {
        val dto = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            originalCurrencyCode = "USD",
            originalAmountMinor = 12345,
            exchangeRateToCny = "7.12340000",
            exchangeRateDate = "2026-05-04",
            exchangeRateSource = "manual",
            fxStatus = "ready",
        )

        val expense = dto.toDomain()
        val entity = dto.toEntity(ledgerId = "owner")

        assertEquals("7.12340000", expense.fxRate)
        assertEquals("7.12340000", expense.exchangeRateToCny)
        assertEquals("2026-05-04", expense.fxRateDate)
        assertEquals("2026-05-04", entity.exchangeRateDate)
        assertEquals("manual", entity.exchangeRateSource)
    }

    @Test
    fun mapsDeletedMediaFlagsAndConfidence() {
        val expense = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            imagePath = "/api/expenses/1/image",
            thumbnailPath = "/api/expenses/1/thumbnail",
            imageDeletedAt = "2026-05-04T05:00:00Z",
            thumbnailDeletedAt = null,
            confidence = 0.42,
        ).toDomain()

        assertEquals(null, expense.imagePath)
        assertEquals(null, expense.thumbnailPath)
        assertEquals("2026-05-04T05:00:00Z", expense.imageDeletedAt)
        assertEquals(0.42, expense.confidence)
    }

    @Test
    fun doesNotPersistDeletedThumbnailPathInRoomCache() {
        val entity = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            thumbnailPath = "/api/expenses/1/thumbnail",
            thumbnailDeletedAt = "2026-05-04T05:00:00Z",
        ).toEntity(ledgerId = "owner")

        assertEquals(null, entity.thumbnailPath)
        assertEquals("2026-05-04T05:00:00Z", entity.thumbnailDeletedAt)
    }

    @Test
    fun baselineAwareToRequestOmitsFxFieldsWhenUnchanged() {
        val baseline = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            originalCurrencyCode = "USD",
            originalAmountMinor = 12345,
            fxRate = "7.12340000",
            fxRateDate = "2026-05-04",
            fxStatus = "ready",
        ).toDomain()

        val request = ExpenseDraft(
            amountCents = null,
            originalCurrencyCode = CurrencyCode.USD,
            originalAmountMinor = 12345,
            merchant = "测试商家",
            category = "其他",
            note = "新加的备注",
            expenseTime = "2026-05-04T04:20:00Z",
            tags = null,
            valueScore = null,
            regretScore = null,
        ).toRequest(baseline = baseline)

        assertEquals(null, request.originalCurrency)
        assertEquals(null, request.originalAmount)
        assertEquals(null, request.spentAt)
        assertEquals(null, request.expenseTime)
        assertEquals("新加的备注", request.note)
    }

    @Test
    fun baselineAwareToRequestSendsFxTimeFieldsWhenTimeChanged() {
        val baseline = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            originalCurrencyCode = "USD",
            originalAmountMinor = 12345,
            fxRate = "7.12340000",
            fxRateDate = "2026-05-04",
            fxStatus = "ready",
        ).toDomain()

        val request = ExpenseDraft(
            amountCents = null,
            originalCurrencyCode = CurrencyCode.USD,
            originalAmountMinor = 12345,
            merchant = "测试商家",
            category = "其他",
            note = "",
            expenseTime = "2026-05-05T04:20:00Z",
            tags = null,
            valueScore = null,
            regretScore = null,
        ).toRequest(baseline = baseline)

        assertEquals(null, request.originalCurrency)
        assertEquals(null, request.originalAmount)
        assertEquals("2026-05-05T04:20:00Z", request.spentAt)
        assertEquals("2026-05-05T04:20:00Z", request.expenseTime)
    }

    @Test
    fun categoryOnlyDraftDoesNotSubmitSyntheticCurrencyFields() {
        val request = ExpenseDraft(
            amountCents = null,
            originalCurrencyCode = null,
            originalAmountMinor = null,
            merchant = null,
            category = "交通",
            note = null,
            expenseTime = null,
            tags = null,
            valueScore = null,
            regretScore = null,
        ).toRequest()

        assertEquals(null, request.originalCurrency)
        assertEquals(null, request.originalAmount)
        assertEquals("交通", request.category)
    }

    @Test
    fun mapsMonthlyTagStatsFromServer() {
        val stats = MonthlyStatsDto(
            month = "2026-05",
            totalAmountCents = 15_800,
            count = 3,
            byCategory = listOf(CategoryStatsDto(category = "吃饭", amountCents = 15_800, count = 3)),
            byTag = listOf(TagStatsDto(tag = "真香", amountCents = 12_000, count = 2)),
        ).toDomain()

        assertEquals(listOf(CategoryStats("餐饮", 15_800, 3)), stats.byCategory)
        assertEquals(listOf(TagStats("真香", 12_000, 2)), stats.byTag)
    }

    @Test
    fun mapsExpenseItemsAndNormalizesCategory() {
        val details = ExpenseItemsResponseDto(
            expenseId = 1,
            parentAmountCents = 1500,
            itemsTotalAmountCents = 1250,
            mismatchCents = 250,
            items = listOf(
                ExpenseItemDto(
                    publicId = "item-1",
                    position = 0,
                    name = "拿铁",
                    quantityText = "1杯",
                    unitPriceCents = 500,
                    amountCents = 500,
                    category = "吃饭",
                    rawText = "拿铁 1杯 5.00",
                    confidence = 0.92,
                    isOcrDraft = true,
                    createdAt = "2026-05-03T04:20:00Z",
                    updatedAt = "2026-05-03T04:20:00Z",
                ),
            ),
        ).toDomain()

        assertEquals(true, details.hasMismatch)
        assertEquals("餐饮", details.items.single().category)
        assertEquals(true, details.items.single().isOcrDraft)
    }

    @Test
    fun mapsExpenseSplitsWithDisabledMemberSignal() {
        val splits = ExpenseSplitsResponseDto(
            expenseId = 1,
            parentAmountCents = 10000,
            splitsTotalAmountCents = 9000,
            mismatchCents = 1000,
            splits = listOf(
                ExpenseSplitDto(
                    publicId = "split-1",
                    position = 0,
                    memberId = 12,
                    accountName = "家人",
                    role = "member",
                    amountCents = 6000,
                    note = "一起吃饭",
                    disabledAt = "2026-05-04T04:20:00Z",
                    createdAt = "2026-05-03T04:20:00Z",
                    updatedAt = "2026-05-03T04:20:00Z",
                ),
            ),
        ).toDomain()

        assertEquals(true, splits.hasMismatch)
        assertEquals(true, splits.splits.single().isDisabledMember)
        assertEquals("家人", splits.splits.single().accountName)
    }

    @Test
    fun itemAndSplitDraftsTrimOptionalFields() {
        val itemRequest = ExpenseItemDraft(
            name = " 拿铁 ",
            quantityText = " 1杯 ",
            unitPriceCents = 500,
            amountCents = 500,
            category = " 吃饭 ",
            rawText = " ",
            confidence = null,
        ).toRequest()
        val splitRequest = ExpenseSplitDraft(
            memberId = 12,
            amountCents = 6000,
            note = " 一起吃饭 ",
        ).toRequest()

        assertEquals("拿铁", itemRequest.name)
        assertEquals("1杯", itemRequest.quantityText)
        assertEquals("餐饮", itemRequest.category)
        assertEquals(null, itemRequest.rawText)
        assertEquals("一起吃饭", splitRequest.note)
    }

    @Test
    fun itemDraftRequiresName() {
        val error = assertFailsWith<RepositoryException> {
            ExpenseItemDraft(
                name = " ",
                quantityText = null,
                unitPriceCents = null,
                amountCents = 500,
                category = "餐饮",
                rawText = null,
                confidence = null,
            ).toRequest()
        }

        assertEquals("请输入商品名称。", error.message)
    }

    @Test
    fun splitDraftRejectsInvalidMemberAndNegativeAmount() {
        val missingMember = assertFailsWith<RepositoryException> {
            ExpenseSplitDraft(memberId = 0, amountCents = 6000, note = null).toRequest()
        }
        val negativeAmount = assertFailsWith<RepositoryException> {
            ExpenseSplitDraft(memberId = 12, amountCents = -1, note = null).toRequest()
        }

        assertEquals("请选择拆账成员。", missingMember.message)
        assertEquals("拆账金额不能为负数。", negativeAmount.message)
    }

    private fun expenseDto(
        publicId: String?,
        category: String = "其他",
        originalCurrencyCode: String? = null,
        originalAmountMinor: Long? = null,
        exchangeRateToCny: String? = null,
        exchangeRateDate: String? = null,
        exchangeRateSource: String? = null,
        fxRate: String? = null,
        fxRateDate: String? = null,
        fxSource: String? = null,
        fxStatus: String? = null,
        imagePath: String? = null,
        thumbnailPath: String? = null,
        imageDeletedAt: String? = null,
        thumbnailDeletedAt: String? = null,
        confidence: Double? = null,
    ): ExpenseDto {
        return ExpenseDto(
            id = 1,
            publicId = publicId,
            amountCents = 3680,
            originalCurrencyCode = originalCurrencyCode,
            originalAmountMinor = originalAmountMinor,
            exchangeRateToCny = exchangeRateToCny,
            exchangeRateDate = exchangeRateDate,
            exchangeRateSource = exchangeRateSource,
            fxRate = fxRate,
            fxRateDate = fxRateDate,
            fxSource = fxSource,
            fxStatus = fxStatus,
            merchant = "测试商家",
            category = category,
            note = "",
            source = "iPhone截图",
            imagePath = imagePath,
            thumbnailPath = thumbnailPath,
            imageDeletedAt = imageDeletedAt,
            thumbnailDeletedAt = thumbnailDeletedAt,
            imageHash = null,
            rawText = "",
            confidence = confidence,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "confirmed",
            expenseTime = "2026-05-04T04:20:00Z",
            createdAt = "2026-05-04T04:00:00Z",
            updatedAt = "2026-05-04T04:30:00Z",
            confirmedAt = "2026-05-04T04:30:00Z",
            rejectedAt = null,
        )
    }
}
