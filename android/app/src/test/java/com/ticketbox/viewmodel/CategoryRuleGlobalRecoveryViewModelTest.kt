package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseCorrectionObservation
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import androidx.lifecycle.viewModelScope
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.repository.CategoryRuleSubmissionPayload
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
class CategoryRuleGlobalRecoveryViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setup() = Dispatchers.setMain(dispatcher)
    @AfterTest fun tearDown() = Dispatchers.resetMain()

    @Test fun aRuleOriginalWithoutAnOwnerDescriptionCannotUseGenericRetry() {
        val binding = LogicalSessionBinding("https://example.test", "owner", "owner", "session", "binding")
        for (type in categoryRuleSubmissionTypes) {
            val row = OutboxRow(43, binding.serverUrl, binding.ledgerId, binding.ownerKey, type,
                "category_rule:17", "{}", 3, PendingMutationStatus.Failed, 1, "client_upgrade_required",
                "2026-09-09T00:00:00Z", null, null, "original-rule-key")
            val state = OutboxStatusUiState(binding = binding, bindingReady = true,
                correctionObservation = ExpenseCorrectionObservation(LedgerAccessContext(binding, true), emptyList()),
                status = OutboxStatus(0, emptyList(), listOf(row)))
            assertFalse(state.offersRetry(row), "A rule original must be interpreted by its command owner")
        }
    }

    @Test fun globalRetryPreservesOriginalCurrencyKeyOccAndRequiresWriteAccess() = runTest(dispatcher) {
        val harness = outboxStatusHarness()
        val request = CategoryRuleRequest("月票", "transport", true, 0, amountMinCents = 1200, homeCurrencyCode = "JPY")
        val payload = OutboxAdapterGraph().categoryRuleSubmissionAdapter.toJson(
            CategoryRuleSubmissionPayload(expectedRowVersion = 3, request = request))
        val id = harness.outbox.enqueue(PendingMutationType.UpdateCategoryRule, "category_rule:17", payload, 3, "original-rule-key")
        harness.outbox.markFailed(id, "client_upgrade_required")
        val original = harness.outbox.observeStatus().first().failed.single()
        val vm = harness.createGlobalViewModel()
        try {
            val ready = vm.uiState.first { it.categoryRules.containsKey(id) }
            assertTrue(ready.offersRetry(original))
            assertEquals(request, ready.categoryRules[id]?.request)
            val access = requireNotNull(ready.correctionObservation.access)
            assertFalse(ready.copy(correctionObservation = ExpenseCorrectionObservation(access.copy(canModify = false), emptyList())).offersRetry(original))
            assertNull(harness.rules.describeSubmission(original.copy(serverUrl = "https://foreign.test")))
            vm.retry(original.copy(ledgerId = "foreign"))
            vm.keepMine(original.copy(targetId = "expense:7"))
            runCurrent()
            assertEquals(original, harness.outbox.observeStatus().first().failed.single())
            assertNull(vm.uiState.value.message)
            vm.retry(original)
            val retried = harness.outbox.observeActiveByTypes(categoryRuleSubmissionTypes)
                .first { it.singleOrNull()?.status == PendingMutationStatus.Pending }.single()
            assertEquals(original.payloadJson, retried.payloadJson)
            assertEquals(original.idempotencyKey, retried.idempotencyKey)
            assertEquals(original.expectedRowVersion, retried.expectedRowVersion)
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    @Test fun currencylessLegacyOriginalCannotRetryButCanStopItsExactLocalRow() = runTest(dispatcher) {
        val harness = outboxStatusHarness()
        val id = harness.outbox.enqueue(PendingMutationType.UpdateCategoryRule, "category_rule:17",
            "{\"expected_row_version\":3,\"keyword\":\"月票\",\"category\":\"transport\",\"enabled\":true,\"priority\":0,\"amount_min_cents\":1200}", 3, "legacy-key")
        harness.outbox.markFailed(id, "client_upgrade_required")
        val original = harness.outbox.observeStatus().first().failed.single()
        val vm = harness.createGlobalViewModel()
        try {
            val ready = vm.uiState.first { it.categoryRules.containsKey(id) }
            assertFalse(ready.offersRetry(original))
            assertEquals(1200L, ready.categoryRules[id]?.request?.amountMinCents)
            assertNull(ready.categoryRules[id]?.request?.homeCurrencyCode)
            vm.retry(original)
            vm.uiState.first { it.message != null && it.busyRowId == null }
            assertEquals(original, harness.outbox.observeStatus().first().failed.single())
            vm.dropFailed(original)
            harness.outbox.observeStatus().first { it.failed.isEmpty() }
            assertTrue(harness.outbox.observeActiveByTypes(categoryRuleSubmissionTypes, includeCompleted = true).first().isEmpty())
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    private fun OutboxStatusHarness.createGlobalViewModel() = OutboxStatusViewModel(outbox, expenseRepository,
        OutboxRecoveryRepositories(debtCreation, null, incomePlans, debtWrites, goalEdits, budgetSaves, recurringItems, rules))
}
