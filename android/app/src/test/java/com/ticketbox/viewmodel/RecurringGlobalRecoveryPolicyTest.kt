package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import kotlin.test.Test
import kotlin.test.assertFalse

class RecurringGlobalRecoveryPolicyTest {
    @Test
    fun currencylessRecurringOriginalCannotBeRetriedFromGlobalSync() {
        val row = OutboxRow(id = 43, serverUrl = "https://example.test", ledgerId = "owner",
            type = PendingMutationType.CreateRecurringItem, targetId = "recurring_item_create:original-key",
            payloadJson = """{"merchant":"月票","baseline_amount_cents":1200}""",
            expectedRowVersion = 0, status = PendingMutationStatus.Failed, retryCount = 0, lastError = null,
            createdAt = "2026-09-09T00:00:00Z", attemptedAt = null, completedAt = null, idempotencyKey = "original-key")
        assertFalse(OutboxStatusUiState().offersRetry(row))
        assertFalse(OutboxStatusUiState().offersRetry(row.copy(type = PendingMutationType.UpdateRecurringItem,
            targetId = "recurring_item:plan-1", expectedRowVersion = 7)))
        assertFalse(OutboxStatusUiState().offersRetry(row.copy(type = PendingMutationType.SetRecurringOccurrencePayment,
            targetId = "recurring_occurrence:plan-1:2026-09")))
    }
}
