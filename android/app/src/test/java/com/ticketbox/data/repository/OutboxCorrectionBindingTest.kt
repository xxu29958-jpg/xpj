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
            assertEquals(id, vm.uiState.value.correctionObservation.corrections.single().row.id)

            fixture.session.switchLedgerForFixture("other", "Other ledger")
            runCurrent()
            assertTrue(fixture.waiting.isCompleted, "The new correction DAO observation is deliberately delayed")
            assertTrue(vm.uiState.value.status.failed.isEmpty(), "The ordinary outbox already switched")
            assertTrue(vm.uiState.value.correctionObservation.corrections.isEmpty(),
                "The new ledger cannot retain a previous ledger's reason or numeric expense link")
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
}

private class CorrectionBindingFixture : ExpensePendingRepositoryOutboxTestBase() {
    val session = seededTokenStore()
    val queue = FakePendingMutationDao()
    val waiting = CompletableDeferred<Unit>()
    val release = CompletableDeferred<Unit>()
    private val dao = object : PendingMutationDao by queue {
        override fun observeActiveByTypes(ownerKey: String, ledgerId: String, types: Collection<String>,
            activeStatuses: Collection<String>) = flow {
            if (ledgerId == "other" && PendingMutationType.CorrectExpense.wireValue in types) {
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
        bindingChanges = binding.sessionStore.observeSession().map { it.toOutboxBinding() })
    val repository = ExpenseRepository(FakeExpenseDao(), binding, deviceNameProvider = { "Test device" },
        offlineMutations = testExpenseOfflineMutationWiring(outbox))
    private val adapters = OutboxAdapterGraph()
    fun model() = OutboxStatusViewModel(outbox, repository,
        DebtCreationRepository(binding.apiProvider, outbox, adapters.debtCreateAdapter),
        incomePlans = IncomePlanRepository(binding.apiProvider, outbox, adapters.incomePlanUpdateAdapter),
        debtAdjustments = DebtAdjustmentRepository(binding.apiProvider, outbox, adapters.debtAdjustmentAdapter))
}
