package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class ManualExpenseSyncRetryTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setup() = Dispatchers.setMain(dispatcher)

    @AfterTest
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun staleRetryCannotRequeueAnUnverifiableOriginalOrWakeTheScheduler() = runTest(dispatcher) {
        for ((refusal, message) in listOf(
            "manual_create_original_unverified" to R.string.ledger_manual_original_unverified,
            "manual_create_original_requires_review:71" to R.string.error_manual_create_original_requires_review,
            "manual_create_original_requires_review" to R.string.error_manual_create_original_requires_review,
        )) {
            var scheduled = 0
            val harness = outboxStatusHarness(onEnqueued = { scheduled += 1 })
            val id = harness.outbox.enqueue(PendingMutationType.CreateExpense, "expense:local:original",
                "{\"client_ref\":\"original\",\"amount_cents\":1200}", 0, "original-key")
            harness.outbox.markFailed(id, "temporary failure")
            val stale = harness.outbox.observeStatus().first().failed.single()
            val vm = harness.viewModel()
            try {
                vm.uiState.first { it.bindingReady && it.status.failed.any { failed -> failed.id == id } }
                assertTrue(vm.uiState.value.offersRetry(stale))
                harness.outbox.markFailed(id, refusal)
                val original = harness.outbox.observeStatus().first().failed.single()
                val scheduledBeforeRetry = scheduled

                // The queued click still carries the old, apparently retryable snapshot.
                vm.retry(stale)
                runCurrent()
                vm.retry(original)
                runCurrent()

                assertFalse(vm.uiState.value.offersRetry(original))
                assertEquals(original, harness.outbox.observeStatus().first().failed.single())
                assertEquals(0, harness.outbox.observeStatus().first().queueDepth)
                assertEquals(scheduledBeforeRetry, scheduled)
                assertEquals(UiText.res(message), vm.uiState.value.message)
                assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
                assertNull(vm.uiState.value.busyRowId)
            } finally {
                vm.viewModelScope.coroutineContext.job.cancelAndJoin()
            }
        }
    }

    @Test
    fun completeLegacyOriginalCanRetryATemporaryFailureWithTheSameMoneyAndKey() = runTest(dispatcher) {
        var scheduled = 0
        val harness = outboxStatusHarness(onEnqueued = { scheduled += 1 })
        val id = harness.outbox.enqueue(PendingMutationType.CreateExpense, "expense:local:legacy",
            "{\"client_ref\":\"legacy\",\"original_currency\":\"CNY\",\"original_amount\":\"12.00\"}",
            0, "legacy-original-key")
        harness.outbox.markFailed(id, "temporary network failure")
        val original = harness.outbox.observeStatus().first().failed.single()
        val vm = harness.viewModel()
        try {
            vm.uiState.first { it.bindingReady && it.status.failed.any { failed -> failed.id == id } }
            assertTrue(vm.uiState.value.offersRetry(original))
            val scheduledBeforeRetry = scheduled

            vm.retry(original)
            runCurrent()

            val retried = harness.outbox.observeActiveByTypes(setOf(PendingMutationType.CreateExpense)).first().single()
            assertEquals(PendingMutationStatus.Pending, retried.status)
            assertEquals(original.id, retried.id)
            assertEquals(original.payloadJson, retried.payloadJson)
            assertEquals(original.idempotencyKey, retried.idempotencyKey)
            assertEquals(original.expectedRowVersion, retried.expectedRowVersion)
            assertEquals(original.ownerKey, retried.ownerKey)
            assertEquals(original.serverUrl, retried.serverUrl)
            assertEquals(original.ledgerId, retried.ledgerId)
            assertEquals(1, harness.outbox.observeStatus().first().queueDepth)
            assertEquals(scheduledBeforeRetry + 1, scheduled)
            assertNull(vm.uiState.value.message)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    private fun OutboxStatusHarness.viewModel() = OutboxStatusViewModel(outbox, expenseRepository,
        OutboxRecoveryRepositories(debtCreation, null, incomePlans, debtAdjustments, goalEdits,
            budgetSaves, recurringItems, rules))
}
