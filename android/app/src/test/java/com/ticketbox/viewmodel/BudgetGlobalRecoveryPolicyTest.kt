package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import kotlin.test.Test
import kotlin.test.assertFalse

class BudgetGlobalRecoveryPolicyTest {
    @Test
    fun unrecognizedBudgetIntentCannotBeRetriedFromGlobalSync() {
        val row = OutboxRow(id = 42, serverUrl = "https://example.test", ledgerId = "owner",
            type = PendingMutationType.SaveMonthlyBudget, targetId = "monthly_budget:2026-09", payloadJson = "{}",
            expectedRowVersion = 0, status = PendingMutationStatus.Failed, retryCount = 0, lastError = null,
            createdAt = "2026-09-08T00:00:00Z", attemptedAt = null, completedAt = null, idempotencyKey = "original-budget-key")
        assertFalse(OutboxStatusUiState().offersRetry(row))
    }
}
