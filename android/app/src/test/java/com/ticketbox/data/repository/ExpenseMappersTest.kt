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
            fixture = ExpenseDtoFixture(category = "吃饭"),
        ).toDomain()

        assertEquals("餐饮", expense.category)
    }

    @Test
    fun mapsForeignCurrencyFieldsFromServerAndDraftRequests() {
        val expense = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            fixture = ExpenseDtoFixture(
                currency = ExpenseDtoCurrencyFixture(
                    originalCurrencyCode = "USD",
                    originalAmountMinor = 12345,
                ),
                fx = ExpenseDtoFxFixture(
                    fxRate = "7.12340000",
                    fxRateDate = "2026-05-04",
                    fxStatus = "ready",
                ),
            ),
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
        ).toManualCreateRequest()

        assertEquals("JPY", request.originalCurrency)
        assertEquals("1200", request.originalAmount)
        assertEquals("2026-05-04T04:00:00Z", request.spentAt)
        // 专用 create DTO（ExpenseManualCreateRequestDto）没有 expectedRowVersion
        // 字段——「manual create 不带 OCC token」从运行时 null-省略约定升级为
        // 编译期结构保证（此前复用 ExpenseUpdateRequest 靠 Moshi 省略 null 键）。
    }

    @Test
    fun mapsLegacyFxAliasesWhenCanonicalFieldsAreMissing() {
        val dto = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            fixture = ExpenseDtoFixture(
                currency = ExpenseDtoCurrencyFixture(
                    originalCurrencyCode = "USD",
                    originalAmountMinor = 12345,
                ),
                legacyFx = ExpenseDtoLegacyFxFixture(
                    exchangeRateToCny = "7.12340000",
                    exchangeRateDate = "2026-05-04",
                    exchangeRateSource = "manual",
                ),
                fx = ExpenseDtoFxFixture(fxStatus = "ready"),
            ),
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
            fixture = ExpenseDtoFixture(
                media = ExpenseDtoMediaFixture(
                    imagePath = "/api/expenses/1/image",
                    thumbnailPath = "/api/expenses/1/thumbnail",
                    imageDeletedAt = "2026-05-04T05:00:00Z",
                    thumbnailDeletedAt = null,
                    confidence = 0.42,
                ),
            ),
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
            fixture = ExpenseDtoFixture(
                media = ExpenseDtoMediaFixture(
                    thumbnailPath = "/api/expenses/1/thumbnail",
                    thumbnailDeletedAt = "2026-05-04T05:00:00Z",
                ),
            ),
        ).toEntity(ledgerId = "owner")

        assertEquals(null, entity.thumbnailPath)
        assertEquals("2026-05-04T05:00:00Z", entity.thumbnailDeletedAt)
    }

    @Test
    fun toEntityPassesThroughUnknownHomeCurrencyCodeVerbatim() {
        // PR#255 R7-2：写侧原码透传 —— 未知码（新版服务端币种）不得被 fromStorageKey 枚举
        // 往返静默改写成 CNY 落缓存（后续同步会把它回写服务端，币种篡改）；blank 才落兜底。
        val entity = expenseDto(publicId = "p1").copy(homeCurrency = "XXX", originalCurrencyCode = "XXX")
            .toEntity(ledgerId = "owner")

        assertEquals("XXX", entity.homeCurrencyCode)
        assertEquals("XXX", entity.originalCurrencyCode)
    }

    @Test
    fun toDomainCarriesRawHomeCurrencyCodeForHonestDisplay() {
        // R7-2：读侧原始码透传到域对象（未知码经 CurrencyDisplay.forRecord 原样亮码），
        // null（旧服务端/手工构造）保持 null 由显示侧回落枚举口径。
        val expense = expenseDto(publicId = "p1").copy(homeCurrency = "JPY").toDomain()

        assertEquals("JPY", expense.homeCurrencyCode)
        assertEquals(CurrencyCode.JPY, expense.homeCurrency)
    }

    @Test
    fun toDomainPassesThroughRawOriginalCurrencyCode() {
        // R13-4：original 原码透传（DTO 侧 originalCurrencyCode 字段 + Entity 缓存侧）——
        // 未知码进原码字段供金额编辑严格解析/禁写，枚举侧维持回落语义不动。
        val expense = expenseDto(publicId = "p1").copy(originalCurrencyCode = "VND").toDomain()

        assertEquals("VND", expense.originalCurrencyCodeRaw)
        assertEquals(CurrencyCode.CNY, expense.originalCurrencyCode) // 枚举回落语义不动

        val entity = expenseDto(publicId = "p1").copy(originalCurrencyCode = "VND")
            .toEntity(ledgerId = "owner")
        val fromCache = entity.toDomain()
        assertEquals("VND", fromCache.originalCurrencyCodeRaw)
    }

    @Test
    fun baselineAwareToRequestOmitsFxFieldsWhenUnchanged() {
        val baseline = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            fixture = ExpenseDtoFixture(
                currency = ExpenseDtoCurrencyFixture(
                    originalCurrencyCode = "USD",
                    originalAmountMinor = 12345,
                ),
                fx = ExpenseDtoFxFixture(
                    fxRate = "7.12340000",
                    fxRateDate = "2026-05-04",
                    fxStatus = "ready",
                ),
            ),
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
        assertEquals(1L, request.expectedRowVersion)
    }

    @Test
    fun baselineAwareToRequestSendsFxTimeFieldsWhenTimeChanged() {
        val baseline = expenseDto(
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            fixture = ExpenseDtoFixture(
                currency = ExpenseDtoCurrencyFixture(
                    originalCurrencyCode = "USD",
                    originalAmountMinor = 12345,
                ),
                fx = ExpenseDtoFxFixture(
                    fxRate = "7.12340000",
                    fxRateDate = "2026-05-04",
                    fxStatus = "ready",
                ),
            ),
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
        assertEquals(1L, request.expectedRowVersion)
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
        ).toManualCreateRequest()

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
            rowVersion = 1L,
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
            rowVersion = 1L,
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
    fun splitDraftRejectsInvalidMemberAndNonPositiveAmount() {
        val missingMember = assertFailsWith<RepositoryException> {
            ExpenseSplitDraft(memberId = 0, amountCents = 6000, note = null).toRequest()
        }
        val negativeAmount = assertFailsWith<RepositoryException> {
            ExpenseSplitDraft(memberId = 12, amountCents = -1, note = null).toRequest()
        }
        val zeroAmount = assertFailsWith<RepositoryException> {
            ExpenseSplitDraft(memberId = 12, amountCents = 0, note = null).toRequest()
        }

        assertEquals("请选择拆账成员。", missingMember.message)
        assertEquals("拆账金额必须大于 0。", negativeAmount.message)
        assertEquals("拆账金额必须大于 0。", zeroAmount.message)
    }

    private data class ExpenseDtoFixture(
        val category: String = "其他",
        val currency: ExpenseDtoCurrencyFixture = ExpenseDtoCurrencyFixture(),
        val legacyFx: ExpenseDtoLegacyFxFixture = ExpenseDtoLegacyFxFixture(),
        val fx: ExpenseDtoFxFixture = ExpenseDtoFxFixture(),
        val media: ExpenseDtoMediaFixture = ExpenseDtoMediaFixture(),
    )

    private data class ExpenseDtoCurrencyFixture(
        val originalCurrencyCode: String? = null,
        val originalAmountMinor: Long? = null,
    )

    private data class ExpenseDtoLegacyFxFixture(
        val exchangeRateToCny: String? = null,
        val exchangeRateDate: String? = null,
        val exchangeRateSource: String? = null,
    )

    private data class ExpenseDtoFxFixture(
        val fxRate: String? = null,
        val fxRateDate: String? = null,
        val fxSource: String? = null,
        val fxStatus: String? = null,
    )

    private data class ExpenseDtoMediaFixture(
        val imagePath: String? = null,
        val thumbnailPath: String? = null,
        val imageDeletedAt: String? = null,
        val thumbnailDeletedAt: String? = null,
        val confidence: Double? = null,
    )

    private fun expenseDto(
        publicId: String?,
        fixture: ExpenseDtoFixture = ExpenseDtoFixture(),
    ): ExpenseDto {
        return ExpenseDto(
            id = 1,
            publicId = publicId,
            amountCents = 3680,
            originalCurrencyCode = fixture.currency.originalCurrencyCode,
            originalAmountMinor = fixture.currency.originalAmountMinor,
            exchangeRateToCny = fixture.legacyFx.exchangeRateToCny,
            exchangeRateDate = fixture.legacyFx.exchangeRateDate,
            exchangeRateSource = fixture.legacyFx.exchangeRateSource,
            fxRate = fixture.fx.fxRate,
            fxRateDate = fixture.fx.fxRateDate,
            fxSource = fixture.fx.fxSource,
            fxStatus = fixture.fx.fxStatus,
            merchant = "测试商家",
            category = fixture.category,
            note = "",
            source = "iPhone截图",
            imagePath = fixture.media.imagePath,
            thumbnailPath = fixture.media.thumbnailPath,
            imageDeletedAt = fixture.media.imageDeletedAt,
            thumbnailDeletedAt = fixture.media.thumbnailDeletedAt,
            imageHash = null,
            rawText = "",
            confidence = fixture.media.confidence,
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
            rowVersion = 1L,
            confirmedAt = "2026-05-04T04:30:00Z",
            rejectedAt = null,
        )
    }
}
