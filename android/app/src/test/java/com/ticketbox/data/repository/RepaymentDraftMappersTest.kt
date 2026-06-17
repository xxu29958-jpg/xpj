package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RepaymentDraftDto
import com.ticketbox.domain.model.RepaymentDraftSource
import com.ticketbox.domain.model.RepaymentDraftStatuses
import com.ticketbox.domain.model.RepaymentNotificationDraft
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class RepaymentDraftMappersTest {
    @Test
    fun dtoMapsToDomainPreservingServerFields() {
        val domain = RepaymentDraftDto(
            publicId = "draft-1",
            source = "alipay",
            amountCents = 50_000,
            homeCurrencyCode = "CNY",
            merchantLabel = "花呗",
            capturedAt = "2026-06-17T08:00:00Z",
            status = RepaymentDraftStatuses.PENDING,
            committedDebtPublicId = null,
            committedRepaymentPublicId = null,
            createdAt = "2026-06-17T08:00:01Z",
            resolvedAt = null,
        ).toDomain()

        assertEquals("draft-1", domain.publicId)
        assertEquals("alipay", domain.source)
        assertEquals(50_000L, domain.amountCents)
        assertEquals("花呗", domain.merchantLabel)
        assertEquals("2026-06-17T08:00:00Z", domain.capturedAt)
        assertTrue(domain.isPending)
    }

    @Test
    fun confirmedDtoMapsCommittedIdsAndResolvedStatus() {
        val domain = RepaymentDraftDto(
            publicId = "draft-2",
            source = "jd",
            amountCents = 120_000,
            homeCurrencyCode = "CNY",
            merchantLabel = null,
            capturedAt = "2026-06-17T08:00:00Z",
            status = RepaymentDraftStatuses.CONFIRMED,
            committedDebtPublicId = "debt-9",
            committedRepaymentPublicId = "rep-9",
            createdAt = "2026-06-17T08:00:01Z",
            resolvedAt = "2026-06-17T09:00:00Z",
        ).toDomain()

        assertEquals("debt-9", domain.committedDebtPublicId)
        assertEquals("rep-9", domain.committedRepaymentPublicId)
        assertEquals("2026-06-17T09:00:00Z", domain.resolvedAt)
        assertTrue(!domain.isPending)
    }

    @Test
    fun notificationDraftMapsToCreateRequestTrimmingBlankLabel() {
        val request = RepaymentNotificationDraft(
            source = RepaymentDraftSource.Jd,
            amountCents = 120_000,
            merchantLabel = "  白条  ",
            capturedAt = "2026-06-17T08:00:00Z",
        ).toCreateRequest(notificationKey = "key-1")

        assertEquals("jd", request.source)
        assertEquals(120_000L, request.amountCents)
        // The repository trims the label before the request leaves the client.
        assertEquals("白条", request.merchantLabel)
        assertEquals("2026-06-17T08:00:00Z", request.capturedAt)
        assertEquals("key-1", request.notificationKey)
    }

    @Test
    fun notificationDraftMapsBlankLabelToNull() {
        val request = RepaymentNotificationDraft(
            source = RepaymentDraftSource.WeChat,
            amountCents = 1_000,
            merchantLabel = "   ",
            capturedAt = null,
        ).toCreateRequest(notificationKey = null)

        assertNull(request.merchantLabel)
        assertNull(request.capturedAt)
        assertNull(request.notificationKey)
        assertEquals("wechat", request.source)
    }

    @Test
    fun confirmRequestCarriesTargetAndRowVersion() {
        val request = confirmRepaymentDraftRequest(targetDebtPublicId = "debt-3", expectedRowVersion = 7L)

        assertEquals("debt-3", request.targetDebtPublicId)
        assertEquals(7L, request.expectedRowVersion)
    }
}
