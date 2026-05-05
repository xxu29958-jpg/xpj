package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseDto
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

        assertEquals("服务器版本过旧，请重启 Windows 后端后再试。", error.message)
    }

    private fun expenseDto(publicId: String?): ExpenseDto {
        return ExpenseDto(
            id = 1,
            publicId = publicId,
            amountCents = 3680,
            merchant = "测试商家",
            category = "其他",
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
