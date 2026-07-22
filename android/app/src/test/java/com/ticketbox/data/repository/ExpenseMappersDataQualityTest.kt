package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseDto
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * 218-B3 data-quality cache contract (PR #230): the Room cache must preserve
 * the server-stored category (before display normalization) and the receipt
 * image presence, or the missing-category / confirmed-without-image filters
 * on cached rows can't match the backend predicates.
 */
class ExpenseMappersDataQualityTest {
    @Test
    fun dtoToEntityPreservesRawCategoryAlongsideNormalizedDisplayValue() {
        // The wire contract is a non-null string; blank is the real-world
        // masked case (normalizeExpenseCategory turns it into 「其他」).
        val entity = expenseDto(category = "").toEntity("owner")

        assertEquals("", entity.categoryRaw)
        assertEquals("其他", entity.category)

        val blankEntity = expenseDto(category = "  ").toEntity("owner")
        assertEquals("  ", blankEntity.categoryRaw)
        assertEquals("其他", blankEntity.category)
    }

    @Test
    fun dtoToEntityDropsImagePathButKeepsItsPresence() {
        assertTrue(expenseDto(imagePath = "receipts/a.jpg").toEntity("owner").hasImage)
        assertFalse(expenseDto(imagePath = null).toEntity("owner").hasImage)
        assertFalse(expenseDto(imagePath = "  ").toEntity("owner").hasImage)
    }

    @Test
    fun entityToDomainRoundTripsQualityColumns() {
        val entity = expenseDto(category = "未分类", imagePath = "receipts/a.jpg").toEntity("owner")
        val domain = entity.toDomain()

        assertEquals("未分类", domain.serverCategory)
        assertEquals("未分类", domain.category)
        assertTrue(domain.hasImage)

        val legacyEntity = entity.copy(categoryRaw = null, hasImage = false)
        val legacyDomain = legacyEntity.toDomain()
        // Pre-v15 cache rows carry NULL categoryRaw — the domain keeps the null
        // so filters fall back to the normalized display value until resync.
        assertNull(legacyDomain.serverCategory)
        assertFalse(legacyDomain.hasImage)
    }

    @Test
    fun dtoToDomainCarriesServerCategoryWithoutNormalization() {
        assertEquals("", expenseDto(category = "").toDomain().serverCategory)
        // normalizeExpenseCategory masks blank into 「其他」 for display, while
        // serverCategory keeps the wire truth; tokens like "none" pass both.
        assertEquals("其他", expenseDto(category = "").toDomain().category)
        assertEquals("none", expenseDto(category = "none").toDomain().serverCategory)
        assertEquals("none", expenseDto(category = "none").toDomain().category)
    }

    private fun expenseDto(
        category: String = "餐饮",
        imagePath: String? = null,
    ): ExpenseDto = ExpenseDto(
        id = 42L,
        publicId = "dq-mapper-public-id",
        amountCents = 12345L,
        merchant = "星巴克",
        category = category,
        note = "",
        source = "Android截图",
        imagePath = imagePath,
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
        expenseTime = "2026-05-20T12:00:00Z",
        createdAt = "2026-05-20T12:00:00Z",
        updatedAt = "2026-05-20T13:00:00Z",
        rowVersion = 1L,
        confirmedAt = "2026-05-20T12:05:00Z",
        rejectedAt = null,
    )
}
