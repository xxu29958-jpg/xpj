package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class SpendingGoalDetailViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun loadReadsCanonicalGoalAndEditStartsFromThatSnapshot() = runTest(dispatcher) {
        val actions = RecordingSpendingGoalActions(
            goalResult = Result.success(spendingGoal(rowVersion = 7L)),
        )
        val viewModel = SpendingGoalDetailViewModel(actions, CapabilityDebtActions())

        viewModel.load(" goal-1 ")
        advanceUntilIdle()
        viewModel.beginEdit()

        assertEquals(listOf("goal-1"), actions.goalCalls)
        assertEquals(7L, viewModel.state.value.goal?.rowVersion)
        assertEquals("200.00", viewModel.state.value.targetAmountInput)
        assertTrue(viewModel.state.value.isEditing)
    }

    @Test
    fun saveUsesLastSeenRowVersionAndCanonicalResponse() = runTest(dispatcher) {
        val updated = spendingGoal(rowVersion = 8L).copy(
            month = "2026-08",
            category = null,
        )
        val actions = RecordingSpendingGoalActions(
            goalResult = Result.success(spendingGoal(rowVersion = 7L)),
            updateResult = Result.success(updated),
        )
        val viewModel = SpendingGoalDetailViewModel(actions, CapabilityDebtActions())
        viewModel.load("goal-1")
        advanceUntilIdle()
        viewModel.beginEdit()
        viewModel.nextMonth()
        viewModel.updateField(SpendingGoalEditField.Name, "八月总支出")
        viewModel.updateField(SpendingGoalEditField.Amount, "500.00")
        viewModel.updateField(SpendingGoalEditField.Category, "")

        viewModel.save()
        advanceUntilIdle()

        assertEquals(
            SpendingGoalUpdateCall(
                publicId = "goal-1",
                update = GoalUpdate(
                    expectedRowVersion = 7L,
                    name = "八月总支出",
                    month = "2026-08",
                    targetAmountCents = 50_000,
                    category = "",
                ),
            ),
            actions.updateCalls.single(),
        )
        assertEquals(8L, viewModel.state.value.goal?.rowVersion)
        assertEquals(1, viewModel.state.value.mutationRevision)
        assertFalse(viewModel.state.value.isEditing)
    }

    @Test
    fun invalidEditDoesNotCallUpdate() = runTest(dispatcher) {
        val actions = RecordingSpendingGoalActions()
        val viewModel = SpendingGoalDetailViewModel(actions, CapabilityDebtActions())
        viewModel.load("goal-1")
        advanceUntilIdle()
        viewModel.beginEdit()
        viewModel.updateField(SpendingGoalEditField.Amount, "")

        viewModel.save()
        advanceUntilIdle()

        assertTrue(actions.updateCalls.isEmpty())
        assertNotNull(viewModel.state.value.formError)
    }

    @Test
    fun saveParsesAmountInLedgerCapability() = runTest(dispatcher) {
        // PR#255 R12-D：编辑保存同走信封 capability —— JPY 账本 "1200" → 1200 minor（不 ×100）。
        val debts = CapabilityDebtActions(
            page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY"),
        )
        val updated = spendingGoal(rowVersion = 8L)
        val actions = RecordingSpendingGoalActions(
            goalResult = Result.success(spendingGoal(rowVersion = 7L)),
            updateResult = Result.success(updated),
        )
        val viewModel = SpendingGoalDetailViewModel(actions, debts)
        viewModel.load("goal-1")
        advanceUntilIdle()
        viewModel.beginEdit()
        // JPY 回填：20000 minor → "20000"（零小数不 ÷100）。
        assertEquals("20000", viewModel.state.value.targetAmountInput)
        viewModel.updateField(SpendingGoalEditField.Amount, "1200")

        viewModel.save()
        advanceUntilIdle()

        assertEquals(1_200L, actions.updateCalls.single().update.targetAmountCents)
    }

    @Test
    fun saveBlockedWhenCapabilityUnsupported() = runTest(dispatcher) {
        // R12-D：capability 在支持集外 → 禁写 + 明示文案，update 不可达。
        val debts = CapabilityDebtActions(
            page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "VND"),
        )
        val actions = RecordingSpendingGoalActions()
        val viewModel = SpendingGoalDetailViewModel(actions, debts)
        viewModel.load("goal-1")
        advanceUntilIdle()
        viewModel.beginEdit()

        assertNull(viewModel.state.value.ledgerCurrency)
        viewModel.save()
        advanceUntilIdle()

        assertTrue(actions.updateCalls.isEmpty())
        assertEquals(
            UiText.res(R.string.currency_unconfirmed_write_blocked),
            viewModel.state.value.formError,
        )
    }

    @Test
    fun viewerCannotEnterEditOrRequestArchive() = runTest(dispatcher) {
        val actions = RecordingSpendingGoalActions(canModify = false)
        val viewModel = SpendingGoalDetailViewModel(actions, CapabilityDebtActions())
        viewModel.load("goal-1")
        advanceUntilIdle()

        viewModel.beginEdit()
        viewModel.requestArchive()

        assertFalse(viewModel.state.value.isEditing)
        assertFalse(viewModel.state.value.showArchiveDialog)
        assertTrue(actions.updateCalls.isEmpty())
        assertTrue(actions.archiveCalls.isEmpty())
    }

    @Test
    fun archiveMarksCompletionAndMutationRevision() = runTest(dispatcher) {
        val actions = RecordingSpendingGoalActions(
            archiveResult = Result.success(spendingGoal(status = "archived", rowVersion = 3L)),
        )
        val viewModel = SpendingGoalDetailViewModel(actions, CapabilityDebtActions())
        viewModel.load("goal-1")
        advanceUntilIdle()

        viewModel.requestArchive()
        viewModel.archive()
        advanceUntilIdle()

        assertEquals(listOf("goal-1"), actions.archiveCalls)
        assertTrue(viewModel.state.value.archiveCompleted)
        assertEquals(1, viewModel.state.value.mutationRevision)
        assertTrue(viewModel.state.value.goal?.isArchived == true)
    }
}
