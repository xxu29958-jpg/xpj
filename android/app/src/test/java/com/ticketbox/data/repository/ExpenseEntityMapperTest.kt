package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseEntityMapperTest {
    @Test
    fun confirmedRoomEntityDisplaysLedgerDataWithoutOriginalImage() {
        val expense = ExpenseEntity(
            serverId = 9,
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            amountCents = 3680,
            merchant = "美团外卖",
            category = "餐饮",
            note = "午饭",
            source = "iPhone截图",
            thumbnailPath = null,
            imageHash = "hash",
            rawText = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "confirmed",
            expenseTime = "2026-05-04T04:20:00Z",
            createdAt = "2026-05-04T04:00:00Z",
            confirmedAt = "2026-05-04T04:30:00Z",
            updatedAt = "2026-05-04T04:30:00Z",
        ).toDomain()

        assertEquals(9, expense.id)
        assertEquals("confirmed", expense.status)
        assertEquals(3680, expense.amountCents)
        assertEquals("美团外卖", expense.merchant)
        assertEquals("餐饮", expense.category)
        assertEquals(null, expense.imagePath)
    }
}
