package com.ticketbox.data.repository

import androidx.lifecycle.viewModelScope
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.viewmodel.OutboxStatusViewModel
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.assertFalse

@OptIn(ExperimentalCoroutinesApi::class)
internal class OutboxCorrectionBindingTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test
    fun delayedCorrectionObservationCannotKeepThePreviousLedgersRecoveryCard() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val fixture = CorrectionBindingFixture()
        var vm: OutboxStatusViewModel? = null
        try {
            val access = requireNotNull(fixture.repository.observeCorrections().first().access)
            val id = fixture.repository.submitCorrection(access.binding,
                successExpenseDto().copy(status = "confirmed", rowVersion = 7).toDomain(),
                ExpenseCorrectionDraft("Private original reason", merchant = "Old ledger merchant")).getOrThrow()
            fixture.outbox.markFailed(id, "correction_delivery_unknown")
            val original = fixture.queue.rows.getValue(id)
            vm = fixture.model()
            runCurrent()
            val oldRow = vm.uiState.value.correctionObservation.corrections.single().row
            assertEquals(id, oldRow.id)
            assertTrue(vm.uiState.value.bindingReady)

            fixture.session.switchLedgerForFixture("other", "Other ledger")
            runCurrent()
            assertTrue(fixture.waiting.isCompleted, "The new correction DAO observation is deliberately delayed")
            assertTrue(vm.uiState.value.status.failed.isEmpty(), "The ordinary outbox already switched")
            assertTrue(vm.uiState.value.correctionObservation.corrections.isEmpty(),
                "The new ledger cannot retain a previous ledger's reason or numeric expense link")
            assertFalse(vm.uiState.value.bindingReady)
            vm.retry(oldRow)
            vm.dropFailed(oldRow)
            runCurrent()
            assertEquals(original, fixture.queue.rows[id])
            assertEquals(null, vm.uiState.value.message)
            fixture.release.complete(Unit)
            runCurrent()
            assertTrue(vm.uiState.value.correctionObservation.corrections.isEmpty())
            fixture.session.switchLedgerForFixture(access.binding.ledgerId, "Original ledger")
            runCurrent()
            assertEquals(id, vm.uiState.value.correctionObservation.corrections.single().row.id)
            assertEquals(original, fixture.queue.rows[id], "Switching views preserves the original offline intent")
        } finally {
            fixture.release.complete(Unit)
            vm?.viewModelScope?.coroutineContext?.job?.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun delayedDebtObservationCannotRestoreThePreviousLedgersAdjustmentDescription() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val fixture = CorrectionBindingFixture(PendingMutationType.RecordDebtAdjustment)
        var vm: OutboxStatusViewModel? = null
        try {
            val access = requireNotNull(fixture.repository.observeCorrections().first().access)
            val id = fixture.outbox.enqueue(PendingMutationType.RecordDebtAdjustment, "debt:old",
                "{\"revision\":99}", 7, "original-adjustment-key")
            fixture.outbox.markFailed(id, "debt_adjustment_payload_unsupported")
            val original = fixture.queue.rows.getValue(id)
            vm = fixture.model()
            runCurrent()
            assertEquals(setOf(id), vm.uiState.value.debtAdjustments.keys)
            fixture.session.switchLedgerForFixture("other", "Other ledger")
            runCurrent()
            assertTrue(fixture.waiting.isCompleted)
            assertTrue(vm.uiState.value.status.failed.isEmpty())
            assertTrue(vm.uiState.value.debtAdjustments.isEmpty())
            assertTrue(vm.uiState.value.waitingDebtAdjustments.isEmpty())
            assertFalse(vm.uiState.value.bindingReady)
            fixture.release.complete(Unit)
            runCurrent()
            assertTrue(vm.uiState.value.bindingReady)
            fixture.session.switchLedgerForFixture(access.binding.ledgerId, "Original ledger")
            runCurrent()
            assertEquals(setOf(id), vm.uiState.value.debtAdjustments.keys)
            assertEquals(original, fixture.queue.rows[id])
        } finally {
            fixture.release.complete(Unit)
            vm?.viewModelScope?.coroutineContext?.job?.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }
}

private class CorrectionBindingFixture(private val delayedType: PendingMutationType = PendingMutationType.CorrectExpense) :
    ExpensePendingRepositoryOutboxTestBase() {
    val session = seededTokenStore()
    val queue = FakePendingMutationDao()
    val waiting = CompletableDeferred<Unit>()
    val release = CompletableDeferred<Unit>()
    private val dao = object : PendingMutationDao by queue {
        override fun observeActiveByTypes(ownerKey: String, ledgerId: String, types: Collection<String>,
            activeStatuses: Collection<String>) = flow {
            if (ledgerId == "other" && delayedType.wireValue in types) {
                waiting.complete(Unit)
                release.await()
            }
            emitAll(queue.observeActiveByTypes(ownerKey, ledgerId, types, activeStatuses))
        }
    }
    private val binding = testServerSessionBinding(TestApiServiceFactory(FakeApiService(mutableListOf(), 0)),
        seededSettingsStore(), session)
    val outbox = OutboxRepository(dao,
        bindingProvider = { binding.sessionStore.currentSession().toOutboxBinding() },
        bindingChanges = binding.sessionStore.observeSession().map { it.toOutboxBinding() }, onRowsDeleted = {})
    val repository = ExpenseRepository(FakeExpenseDao(), binding, deviceNameProvider = { "Test device" },
        offlineMutations = testExpenseOfflineMutationWiring(outbox))
    private val adapters = OutboxAdapterGraph()
    fun model() = OutboxStatusViewModel(outbox, repository, com.ticketbox.viewmodel.OutboxRecoveryRepositories(
        DebtCreationRepository(binding.apiProvider, outbox, adapters.debtCreateAdapter),
        recurringOccurrences = null,
        incomePlans = IncomePlanRepository(binding.apiProvider, outbox, adapters.incomePlanUpdateAdapter),
        debtAdjustments = DebtAdjustmentRepository(binding.apiProvider, outbox, adapters.debtAdjustmentAdapter),
        goalEdits = GoalEditRepository(binding.apiProvider, outbox, adapters.goalUpdateAdapter, adapters.goalReceiptAdapter)))
}
