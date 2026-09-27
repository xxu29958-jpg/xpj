package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtReadResourceDenial
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.SnapshotAccessDenial
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.test.resetMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtReadViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test fun sharedRefusalRemovesReadAndLateListButPreservesOriginalCreationDraftUntilRetry() = runTest(dispatcher) {
        val actions = FakeDebtActions(listResult = Result.success(listOf(sampleDebt("original"))))
        val model = DebtListViewModel(actions, actions.creation, actions.writes)
        advanceUntilIdle()
        model.updateDraftField(DebtDraftField.Counterparty, "原对象")
        model.updateDraftField(DebtDraftField.Amount, "1200")
        val draft = model.state.value.addDraft
        val gate = CompletableDeferred<Unit>()
        actions.listGate = gate
        model.refresh()
        runCurrent()
        actions.readDenials.emit(SnapshotAccessDenial(requireNotNull(actions.creation.currentAccess()).binding,
            RepositoryException("无权读取", httpStatusCode = 403), 1))
        gate.complete(Unit)
        advanceUntilIdle()
        assertTrue(model.state.value.debts.isEmpty())
        assertNull(model.state.value.fetchedAt)
        assertEquals(draft, model.state.value.addDraft)
        assertFalse(model.state.value.homeCurrencyResolved)
        actions.listGate = null
        model.refresh()
        advanceUntilIdle()
        assertEquals("original", model.state.value.debts.single().publicId)
        assertEquals("2026-09-27T01:00:00Z", model.state.value.fetchedAt)
        assertFalse(model.state.value.fromCache)
        assertEquals(draft.amountYuanInput, model.state.value.addDraft.amountYuanInput)
    }

    @Test fun offlineOriginalReadKeepsItsSourceTimeAndRowsWhenRetryFails() = runTest(dispatcher) {
        val actions = FakeDebtActions(listResult = Result.success(listOf(sampleDebt("original")))).apply { fromCache = true }
        val model = DebtListViewModel(actions, actions.creation, actions.writes)
        advanceUntilIdle()
        assertTrue(model.state.value.fromCache)
        val time = model.state.value.fetchedAt
        actions.listResult = Result.failure(java.io.IOException("still offline"))
        model.refresh()
        advanceUntilIdle()
        assertEquals(time, model.state.value.fetchedAt)
        assertEquals("original", model.state.value.debts.single().publicId)
        assertTrue(model.state.value.fromCache)
        assertTrue(model.state.value.error != null)
    }

    @Test fun resourceNotFoundOnlyRemovesItsDebtWhileOtherReadRowsStayVisible() = runTest(dispatcher) {
        val actions = FakeDebtActions(listResult = Result.success(listOf(sampleDebt("gone"), sampleDebt("kept"))))
        val model = DebtListViewModel(actions, actions.creation, actions.writes)
        advanceUntilIdle()
        actions.resourceDenials.emit(DebtReadResourceDenial(requireNotNull(actions.creation.currentAccess()).binding,
            "gone", RepositoryException("记录不存在", httpStatusCode = 404), 1))
        advanceUntilIdle()
        assertEquals(listOf("kept"), model.state.value.debts.map { it.publicId })
        assertEquals("2026-09-27T01:00:00Z", model.state.value.fetchedAt)
    }

    @Test fun missingResourceDuringColdOrRefreshReadStillShowsOtherCurrentDebtsAndRetiresLateRows() = runTest(dispatcher) {
        for (cold in listOf(true, false)) {
            val other = sampleDebt("kept").copy(homeCurrencyCode = "JPY", originalCurrencyCode = "JPY")
            val actions = FakeDebtActions(listResult = Result.success(listOf(
                other.copy(publicId = "gone"), other,
            )))
            val gate = CompletableDeferred<Unit>()
            if (cold) actions.listGate = gate
            val model = DebtListViewModel(actions, actions.creation, actions.writes)
            advanceUntilIdle()
            if (!cold) {
                model.updateDraftField(DebtDraftField.Amount, "1200")
                model.updateDraftField(DebtDraftField.Counterparty, "原对象")
                actions.listGate = gate
                model.refresh()
                runCurrent()
            }
            val draft = model.state.value.addDraft
            assertTrue(model.state.value.isLoading)
            val current = other.copy(rowVersion = other.rowVersion + 1, remainingAmountCents = 7_000)
            actions.listResult = Result.success(listOf(current))
            actions.listGate = null
            try {
                actions.resourceDenials.emit(DebtReadResourceDenial(requireNotNull(actions.creation.currentAccess()).binding,
                    "gone", RepositoryException("记录不存在", httpStatusCode = 404), 1))
                advanceUntilIdle()
                assertEquals(listOf(current), model.state.value.debts)
                assertFalse(model.state.value.isLoading)
                assertEquals("2026-09-27T01:00:00Z", model.state.value.fetchedAt)
                if (!cold) assertEquals(draft, model.state.value.addDraft)
            } finally { gate.complete(Unit) }
            advanceUntilIdle()
            assertEquals(listOf(current), model.state.value.debts, "Late rows cannot restore the denied resource or its old balance")
            assertEquals("JPY", model.state.value.debts.single().homeCurrencyCode)
            assertTrue(actions.writes.saveCalls.isEmpty())
        }
    }

    @Test fun actionKeepsOriginalTargetOccAndTextUntilExplicitReviewOrCancel() = runTest(dispatcher) {
        val actions = FakeDebtActions().apply {
            detailResult = Result.success(sampleDebt().copy(homeCurrencyCode = "JPY", originalCurrencyCode = "JPY"))
        }
        val model = DebtDetailViewModel(actions, actions.writes)
        model.loadDebt("original")
        advanceUntilIdle()
        model.openAction(DebtAction.Adjustment)
        model.updateActionInput(amount = "1200", reason = "原原因")
        val original = requireNotNull(model.state.value.actionTarget)
        actions.detailResult = Result.success(original.copy(rowVersion = 8, remainingAmountCents = 70_000))
        model.refresh()
        advanceUntilIdle()
        assertEquals(8L, model.state.value.debt?.rowVersion)
        assertEquals(original, model.state.value.actionTarget)
        actions.readDenials.emit(SnapshotAccessDenial(requireNotNull(actions.writes.currentAccess()).binding,
            RepositoryException("无权读取", httpStatusCode = 403), 1))
        advanceUntilIdle()
        assertNull(model.state.value.debt)
        assertEquals("1200", model.state.value.amountInput)
        assertEquals("原原因", model.state.value.reasonInput)
        assertEquals(original, model.state.value.actionTarget)
        assertEquals(com.ticketbox.domain.model.CurrencyCode.JPY, model.state.value.amountInputCurrency)
        assertTrue(actions.writes.saveCalls.isEmpty())
        model.refresh()
        advanceUntilIdle()
        actions.writes.saveResult = Result.failure(java.io.IOException("Room publication unavailable"))
        model.submit()
        advanceUntilIdle()
        assertEquals("1200", model.state.value.amountInput)
        assertEquals(original, actions.writes.saveCalls.single().debt)
        assertEquals(original.rowVersion, actions.writes.saveCalls.single().debt.rowVersion)
        model.updateActionInput(reviewLatest = true)
        assertEquals(8L, model.state.value.actionTarget?.rowVersion)
        assertEquals("1200", model.state.value.amountInput)
        assertEquals("原原因", model.state.value.reasonInput)
        assertEquals(com.ticketbox.domain.model.CurrencyCode.JPY, model.state.value.amountInputCurrency)
        assertFalse(model.state.value.canReviewAction)
        model.submit()
        advanceUntilIdle()
        assertEquals(8L, actions.writes.saveCalls.last().debt.rowVersion)
        assertEquals(1_200L, actions.writes.saveCalls.last().amountCents)
        model.dismissAction()
        assertNull(model.state.value.actionTarget)
    }

    @Test fun cachedDetailWithNoOriginalWriteKeepsOfflineAdjustmentAvailable() = runTest(dispatcher) {
        val actions = FakeDebtActions().apply {
            fromCache = true
            detailResult = Result.success(sampleDebt().copy(homeCurrencyCode = "JPY", originalCurrencyCode = "JPY"))
        }
        val model = DebtDetailViewModel(actions, actions.writes)
        model.loadDebt("debt-1")
        advanceUntilIdle()
        assertTrue(model.state.value.fromCache)
        assertNull(model.state.value.writeMessage)
        assertTrue(model.state.value.canWriteActions)
        model.openAction(DebtAction.Adjustment)
        model.updateActionInput(amount = "1200", reason = "保留离线调整")
        model.submit()
        advanceUntilIdle()
        val original = actions.writes.saveCalls.single()
        assertEquals(1_200L, original.amountCents)
        assertEquals("JPY", original.debt.homeCurrencyCode)
        assertEquals("保留离线调整", original.reason)
    }
    @Test fun cachedHigherVersionDoesNotClearAcceptedOriginalWriteRefreshGate() = runTest(dispatcher) {
        val actions = FakeDebtActions().apply {
            fromCache = true
            detailResult = Result.success(sampleDebt().copy(rowVersion = 8))
        }
        val original = pendingAdjustment(status = com.ticketbox.data.local.PendingMutationStatus.Done)
        actions.writes.rows.value = listOf(original)
        val model = DebtDetailViewModel(actions, actions.writes)
        model.loadDebt("debt-1")
        advanceUntilIdle()
        assertEquals(8L, model.state.value.debt?.rowVersion)
        assertEquals(7L, model.state.value.writeRefreshAfterVersion)
        assertFalse(model.state.value.canWriteActions)
        assertEquals(original, actions.writes.rows.value.single())
        actions.fromCache = false
        model.refresh()
        advanceUntilIdle()
        assertNull(model.state.value.writeRefreshAfterVersion)
        assertTrue(model.state.value.canWriteActions)
    }

    @Test fun cachedClearedMemberDebtCannotTriggerNewSettlementCelebration() = runTest(dispatcher) {
        val actions = FakeDebtActions().apply {
            detailResult = Result.success(sampleDebt().copy(counterpartyType = com.ticketbox.domain.model.DebtCounterpartyTypes.MEMBER,
                viewerIsDebtor = true))
        }
        val model = DebtDetailViewModel(actions, actions.writes)
        model.loadDebt("member")
        advanceUntilIdle()
        actions.fromCache = true
        actions.detailResult = actions.detailResult.map { it.copy(status = com.ticketbox.domain.model.DebtLinkStatuses.CLEARED,
            remainingAmountCents = 0, paidAmountCents = it.principalAmountCents) }
        model.refresh()
        advanceUntilIdle()
        assertNull(model.celebration.value)
        actions.fromCache = false
        model.refresh()
        advanceUntilIdle()
        assertTrue(model.celebration.value != null)
    }

}
