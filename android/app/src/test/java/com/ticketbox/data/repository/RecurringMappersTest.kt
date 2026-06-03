package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.domain.model.RecurringCandidate
import kotlin.test.Test
import kotlin.test.assertEquals

class RecurringMappersTest {
    @Test
    fun recurringItemDtoMapsToDomain() {
        val item = RecurringItemDto(
            publicId = "recurring-1",
            ledgerId = "owner",
            merchant = "ChatGPT Plus",
            merchantKey = "chatgpt plus",
            frequency = "monthly",
            baselineAmountCents = 20000,
            lastAmountCents = 20000,
            occurrenceCount = 3,
            lastSeenAt = "2026-05-05T12:00:00Z",
            nextExpectedDate = "2026-06-05",
            status = "active",
            confidence = "high",
            source = "candidate",
            anomalyStatus = "higher_than_average",
            currentMonthAmountCents = 28000,
            historicalAverageAmountCents = 20000,
            amountDeltaPercent = 40,
            createdAt = "2026-05-13T00:00:00Z",
            updatedAt = "2026-05-13T00:00:00Z",
            rowVersion = 1L,
            pausedAt = null,
            archivedAt = null,
        ).toDomain()

        assertEquals("recurring-1", item.publicId)
        assertEquals("owner", item.ledgerId)
        assertEquals("ChatGPT Plus", item.merchant)
        assertEquals(20000L, item.baselineAmountCents)
        assertEquals("2026-06-05", item.nextExpectedDate)
        assertEquals("active", item.status)
        assertEquals("higher_than_average", item.anomalyStatus)
        assertEquals(28000L, item.currentMonthAmountCents)
        assertEquals(40, item.amountDeltaPercent)
    }

    @Test
    fun recurringCandidateMapsToConfirmRequest() {
        val request = RecurringCandidate(
            merchant = "ChatGPT Plus",
            amountCents = 20000,
            occurrenceCount = 3,
            lastSeenAt = "2026-05-05T12:00:00Z",
            confidence = "high",
            reason = "近 3 个月金额接近，每月出现",
        ).toConfirmRequest(nextExpectedDate = "2026-06-05")

        assertEquals("ChatGPT Plus", request.merchant)
        assertEquals(20000L, request.amountCents)
        assertEquals(3, request.occurrenceCount)
        assertEquals("2026-05-05T12:00:00Z", request.lastSeenAt)
        assertEquals("monthly", request.frequency)
        assertEquals("2026-06-05", request.nextExpectedDate)
    }
}
