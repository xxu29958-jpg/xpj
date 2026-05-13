package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.CategoryStatsDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.TagStatsDto
import com.ticketbox.domain.model.CategoryStats
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

    private fun expenseDto(publicId: String?, category: String = "其他"): ExpenseDto {
        return ExpenseDto(
            id = 1,
            publicId = publicId,
            amountCents = 3680,
            merchant = "测试商家",
            category = category,
            note = "",
            source = "iPhone截图",
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = "",
            confidence = null,
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
