package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class CategoryRuleOriginalIntentTest {
    private val adapters = OutboxAdapterGraph()
    private val request = CategoryRuleRequest("旅行", "交通", true, 10, 1200, null, homeCurrencyCode = "JPY")
    private val original = CategoryRuleSubmissionPayload(expectedRowVersion = 4, request = request)
    private val row = OutboxRow(1, "https://rule.example", "owner", "identity",
        PendingMutationType.UpdateCategoryRule, "category_rule:7", "", 4,
        PendingMutationStatus.Failed, 1, "client_upgrade_required", "2026-09-09T00:00:00Z", null, null, "original-key")

    @Test fun originalRuleCurrencyAndExplicitClearedBoundSurviveRoundTrip() {
        val json = adapters.categoryRuleSubmissionAdapter.toJson(original)
        val restored = requireNotNull(adapters.categoryRuleSubmissionAdapter.fromJson(json))
        assertEquals(original, restored)
        assertEquals(1200L, restored.request.amountMinCents)
        assertEquals("JPY", restored.request.homeCurrencyCode)
        val patchJson = adapters.categoryRuleUpdateAdapter.toJson(restored.updateRequest())
        assertTrue(patchJson.contains("\"amount_max_cents\":null"))
    }

    @Test fun legacyFlatIntentKeepsItsAmountAndCannotRetryOrPretendDone() {
        val raw = """{"expected_row_version":0,"amount_min_cents":1200}"""
        val pending = describeCategoryRuleSubmission(row.copy(payloadJson = raw), adapters.categoryRuleSubmissionAdapter,
            adapters.categoryRuleUpdateAdapter, adapters.categoryRuleReceiptAdapter)
        assertEquals(1200L, pending.request?.amountMinCents)
        assertEquals(null, pending.request?.homeCurrencyCode)
        assertFalse(pending.canRetry)
        assertEquals(raw, pending.row.payloadJson)
    }

    @Test fun receiptMustBeForTheOriginalBoundsCurrencyAndVersion() {
        val receipt = CategoryRuleDto(7, "旅行", "交通", true, 10, 1200, null,
            createdAt = "", updatedAt = "", rowVersion = 5, homeCurrencyCode = "JPY")
        assertTrue(original.acceptsReceipt(row, receipt))
        assertFalse(original.acceptsReceipt(row, receipt.copy(homeCurrencyCode = "CNY")))
        assertFalse(original.acceptsReceipt(row, receipt.copy(rowVersion = 6)))
        assertFalse(original.acceptsReceipt(row, receipt.copy(amountMaxCents = 5000)))
        assertFalse(original.acceptsReceipt(row, receipt.copy(id = 8)))
    }
}
