package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExchangeRateRequestDto
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.job
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ManualRateGlobalRecoveryViewModelTest {
    private val request = ExchangeRateRequestDto("JPY", "USD", "2026-09-01", "0.0069", "manual", 0)

    @Test fun globalRetryUsesTheOwnerAndRetainsOriginalPairDateAmountKeyAndOcc() = budgetTest {
        val harness = outboxStatusHarness()
        val binding = requireNotNull(harness.expenseRepository.captureDeferredLedgerBinding())
        val id = harness.budgetSaves.enqueueRate(binding, "2026-09", request, null).getOrThrow()
        harness.outbox.markFailed(id, "client_upgrade_required")
        val original = harness.outbox.observeStatus().first().failed.single()
        val vm = harness.rateGlobalViewModel()
        try {
            val state = vm.uiState.first { it.bindingReady && it.manualRates[id]?.canRetry == true }
            assertEquals(request, state.manualRates[id]?.intent?.request)
            assertTrue(state.offersRetry(original))
            vm.keepMine(original)
            assertEquals(original, harness.outbox.observeStatus().first().failed.single())
            vm.retry(original)
            val replay = harness.outbox.observeActiveByTypes(setOf(PendingMutationType.SaveManualExchangeRate))
                .first { it.singleOrNull()?.status == PendingMutationStatus.Pending }.single()
            assertEquals(original.payloadJson, replay.payloadJson)
            assertEquals(original.idempotencyKey, replay.idempotencyKey)
            assertEquals(original.expectedRowVersion, replay.expectedRowVersion)
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    @Test fun unverifiedDoneCannotReportSuccessOrRetryAndCanBeStoppedLocally() = budgetTest {
        val harness = outboxStatusHarness()
        val binding = requireNotNull(harness.expenseRepository.captureDeferredLedgerBinding())
        val id = harness.budgetSaves.enqueueRate(binding, "2026-09", request, null).getOrThrow()
        harness.outbox.markDone(id)
        val vm = harness.rateGlobalViewModel()
        try {
            val state = vm.uiState.first { it.bindingReady && it.manualRates[id]?.canDrop == true }
            val pending = requireNotNull(state.manualRates[id])
            assertFalse(pending.isConfirmed)
            assertFalse(state.offersRetry(pending.row))
            vm.dropFailed(pending.row)
            vm.uiState.first { id !in it.manualRates && it.busyRowId == null }
            assertTrue(harness.budgetSaves.observeRates(binding).first().isEmpty())
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }
}

private fun OutboxStatusHarness.rateGlobalViewModel() = OutboxStatusViewModel(outbox, expenseRepository,
    OutboxRecoveryRepositories(debtCreation, null, incomePlans, debtAdjustments, goalEdits, budgetSaves, recurringItems, rules))
