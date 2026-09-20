package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BillSplitSentDto
import kotlin.test.Test
import kotlin.test.assertEquals

class BillSplitMappersTest {
    @Test
    fun `sent DTO without current agreement falls back to original invitation amount`() {
        val dto = BillSplitSentDto(
            publicId = "legacy",
            status = "accepted",
            amountCents = 400L,
            merchantSnapshot = null,
            categorySuggestion = null,
            expenseTimeSnapshot = null,
            expiresAt = "2026-09-21T00:00:00Z",
            createdAt = "2026-09-20T00:00:00Z",
            acceptedAt = "2026-09-20T01:00:00Z",
            rejectedAt = null,
            cancelledAt = null,
            expiredAt = null,
            receiverAccountId = 2L,
            receiverDisplayNameSnapshot = "家人",
            senderExpenseId = 7L,
            homeCurrencyCode = "CNY",
        )

        val result = dto.toDomain()
        assertEquals(400L, result.currentAgreedShareAmountCents)
        assertEquals(400L, result.amountCents)
    }
}
