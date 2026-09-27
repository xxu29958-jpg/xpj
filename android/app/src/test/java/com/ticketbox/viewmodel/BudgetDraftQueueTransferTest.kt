package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.repository.BudgetSavePayload
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingBudgetSave
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class BudgetDraftQueueTransferTest {
    @Test
    fun oldAndroidSnapshotCannotResubmitTheQueuedOriginal() = budgetTest {
        val state = SavedStateHandle()
        val owner = FakeBudgetActions(budget = budget().copy(homeCurrencyCode = "JPY", nonMonthlyAmountCents = 0))
        val first = BudgetViewModel(owner, "2026-05", savedStateHandle = state)
        advanceUntilIdle()
        first.updateTotalAmount(" 1200 ")
        val oldSnapshot = SavedStateHandle(state.keys().associateWith { state.get<Any?>(it) })
        first.save()
        advanceUntilIdle()
        assertEquals(1, owner.commands.savedRequests.size)
        owner.commands.saves.value = listOf(pendingBudget())
        owner.budget = owner.budget.copy(homeCurrencyCode = "CNY", rowVersion = 3)
        val restored = BudgetViewModel(owner, "2026-05", savedStateHandle = oldSnapshot)
        advanceUntilIdle()
        assertFalse(restored.uiState.value.formDirty)
        assertTrue(restored.uiState.value.hasPendingSave)
        assertEquals("JPY", restored.uiState.value.form.homeCurrencyCode)
        assertEquals(1L, restored.uiState.value.form.expectedRowVersion)
        restored.save()
        advanceUntilIdle()
        assertEquals(1, owner.commands.savedRequests.size)
        val accepted = budget(totalAmountCents = 1200).copy(homeCurrencyCode = "JPY", rowVersion = 2)
        owner.commands.saves.value = listOf(pendingBudget().let { it.copy(row = it.row.copy(status = PendingMutationStatus.Done), receipt = accepted) })
        advanceUntilIdle()
        assertFalse(restored.uiState.value.hasPendingSave)
        assertEquals("CNY", restored.uiState.value.budget?.homeCurrencyCode)
        assertEquals(1, owner.commands.savedRequests.size)
    }

    @Test
    fun completedEarlierEditDoesNotEraseANewRawDraft() = budgetTest {
        val state = SavedStateHandle()
        val owner = FakeBudgetActions(budget = budget().copy(homeCurrencyCode = "JPY", nonMonthlyAmountCents = 0))
        val vm = BudgetViewModel(owner, "2026-05", savedStateHandle = state)
        advanceUntilIdle()
        vm.updateTotalAmount(" 1500 ")
        val original = vm.uiState.value.form
        owner.commands.saves.value = listOf(pendingBudget().let { it.copy(
            row = it.row.copy(status = PendingMutationStatus.Done),
            receipt = budget(totalAmountCents = 1200).copy(homeCurrencyCode = "JPY", rowVersion = 2),
        ) })
        advanceUntilIdle()
        assertEquals(original, vm.uiState.value.form)
        assertTrue(vm.uiState.value.formDirty)
        val restored = BudgetViewModel(owner, "2026-05", savedStateHandle = state)
        advanceUntilIdle()
        assertEquals(original, restored.uiState.value.form)
        assertTrue(restored.uiState.value.formDirty)
        assertEquals(0, owner.commands.savedRequests.size)
    }

    @Test fun acceptedSaveRetiresVisibleBudgetAndLateInsightsReadWithoutErasingANewerDraft() = budgetTest {
        val owner = FakeBudgetActions(budget = budget().copy(homeCurrencyCode = "JPY", nonMonthlyAmountCents = 0))
        val editor = BudgetViewModel(owner, "2026-05")
        val insights = StatsBudgetViewModel(owner)
        advanceUntilIdle()
        insights.refresh("2026-05")
        advanceUntilIdle()
        editor.updateTotalAmount(" 1500 ")
        val draft = editor.uiState.value.form
        val late = CompletableDeferred<Result<com.ticketbox.domain.model.BudgetMonthly>>()
        owner.monthlyBudgetResponder = { late.await() }
        insights.refresh("2026-05", force = true)
        advanceUntilIdle()
        owner.monthlyBudgetResponder = { Result.failure(java.net.ConnectException("Offline after accepted save")) }
        val accepted = budget(totalAmountCents = 1200).copy(homeCurrencyCode = "JPY", rowVersion = 2)
        val original = pendingBudget().let { it.copy(row = it.row.copy(status = PendingMutationStatus.Done), receipt = accepted) }
        owner.commands.saves.value = listOf(original)
        advanceUntilIdle()
        late.complete(Result.success(owner.budget))
        advanceUntilIdle()
        assertNull(editor.uiState.value.budget)
        assertNull(editor.uiState.value.fetchedAt)
        assertNull(insights.uiState.value.budgetProgress)
        assertNull(insights.uiState.value.fetchedAt)
        assertEquals(draft, editor.uiState.value.form)
        assertTrue(editor.uiState.value.formDirty)
        assertEquals(listOf(original), owner.commands.saves.value)
        owner.monthlyBudgetResponder = { Result.success(accepted) }
        editor.refresh()
        insights.refresh("2026-05")
        advanceUntilIdle()
        assertEquals(1200L, editor.uiState.value.budget?.totalAmountCents)
        assertEquals(1200L, insights.uiState.value.budgetProgress?.budgetCents)
        assertEquals(draft, editor.uiState.value.form)
        assertEquals(listOf(original), owner.commands.saves.value)
    }

    @Test fun recoveringAnOlderReceiptKeepsTheAlreadyReadBudgetAndItsOriginalTime() = budgetTest {
        for (queryVersion in listOf(2L, 3L)) {
            val accepted = budget(totalAmountCents = 1200).copy(homeCurrencyCode = "JPY", rowVersion = 2)
            val queried = accepted.copy(rowVersion = queryVersion,
                totalAmountCents = if (queryVersion == 2L) 1200 else 2600)
            val owner = FakeBudgetActions(budget = queried)
            owner.commands.saves.value = listOf(pendingBudget())
            val editor = BudgetViewModel(owner, "2026-05")
            val insights = StatsBudgetViewModel(owner)
            advanceUntilIdle()
            insights.refresh("2026-05")
            advanceUntilIdle()
            assertEquals(queried, editor.uiState.value.budget)
            assertEquals(queried.totalAmountCents, insights.uiState.value.budgetProgress?.budgetCents)
            val readTime = editor.uiState.value.fetchedAt

            owner.monthlyBudgetResponder = { Result.failure(java.net.ConnectException("Offline after receipt recovery")) }
            owner.commands.saves.value = listOf(pendingBudget().let {
                it.copy(row = it.row.copy(status = PendingMutationStatus.Done), receipt = accepted)
            })
            advanceUntilIdle()

            assertEquals(queried, editor.uiState.value.budget,
                "Recovering the original receipt cannot erase a same-or-newer authoritative query")
            assertEquals(readTime, editor.uiState.value.fetchedAt)
            assertEquals(queried.totalAmountCents, insights.uiState.value.budgetProgress?.budgetCents)
            assertEquals(readTime, insights.uiState.value.fetchedAt)
            assertEquals(queryVersion, editor.uiState.value.form.expectedRowVersion)
            assertEquals(queried.totalAmountCents.toString(), editor.uiState.value.form.totalAmount)
            assertFalse(editor.uiState.value.hasPendingSave)
            assertEquals(0, owner.commands.savedRequests.size)
        }
    }

    @Test fun firstObservedDoneWithdrawsOnlyOlderBudgetQueriesAndKeepsTheOriginalSaveAndDraft() = budgetTest {
        for (version in listOf(1L, 2L, 3L)) {
            val accepted = budget(totalAmountCents = 1200).copy(homeCurrencyCode = "JPY", rowVersion = 2)
            val queried = accepted.copy(rowVersion = version, totalAmountCents = 900 + version * 100)
            val owner = FakeBudgetActions(queried)
            val original = pendingBudget().let {
                it.copy(row = it.row.copy(status = PendingMutationStatus.Done), receipt = accepted)
            }
            owner.commands.saves.value = listOf(original)
            val firstSaves = CompletableDeferred<Unit>()
            val delayedOwner = object : BudgetActions by owner {
                override fun observeSaves(expectedBinding: LogicalSessionBinding): Flow<List<PendingBudgetSave>> = flow {
                    firstSaves.await()
                    emitAll(owner.commands.saves)
                }
            }
            val editor = BudgetViewModel(delayedOwner, "2026-05")
            val insights = StatsBudgetViewModel(delayedOwner)
            advanceUntilIdle()
            insights.refresh("2026-05")
            advanceUntilIdle()
            editor.updateTotalAmount("1500")
            val draft = editor.uiState.value.form
            assertEquals(queried, editor.uiState.value.budget)
            assertEquals(queried.totalAmountCents, insights.uiState.value.budgetProgress?.budgetCents)
            val fetchedAt = insights.uiState.value.fetchedAt
            owner.monthlyBudgetResponder = { Result.failure(java.net.ConnectException("Offline after accepted save")) }
            firstSaves.complete(Unit)
            advanceUntilIdle()

            if (version < 2) {
                assertNull(editor.uiState.value.budget, "Plans and Budget must also handle the first Done emission")
                assertNull(editor.uiState.value.fetchedAt)
                assertNull(insights.uiState.value.budgetProgress, "The first Done emission must retire an older visible query")
                assertNull(insights.uiState.value.fetchedAt)
            } else {
                assertEquals(queried, editor.uiState.value.budget)
                assertEquals(fetchedAt, editor.uiState.value.fetchedAt)
                assertEquals(queried.totalAmountCents, insights.uiState.value.budgetProgress?.budgetCents)
                assertEquals(fetchedAt, insights.uiState.value.fetchedAt)
            }
            assertEquals(listOf(original), owner.commands.saves.value)
            assertEquals(draft, editor.uiState.value.form)
            assertTrue(editor.uiState.value.formDirty)
            assertTrue(owner.commands.savedRequests.isEmpty())
            owner.monthlyBudgetResponder = { Result.success(accepted.copy(rowVersion = 3)) }
            insights.refresh("2026-05", force = true)
            advanceUntilIdle()
            assertEquals(1200L, insights.uiState.value.budgetProgress?.budgetCents)
        }
    }

    @Test fun acceptedSaveReadRecoveryUpdatesTheBudgetWithoutResendingOrReplacingANewerDraft() = budgetTest {
        val owner = FakeBudgetActions(budget = budget().copy(homeCurrencyCode = "JPY"))
        val editor = BudgetViewModel(owner, "2026-05")
        advanceUntilIdle()
        editor.updateTotalAmount(" 1500 ")
        val draft = editor.uiState.value.form
        val accepted = budget(totalAmountCents = 1200).copy(homeCurrencyCode = "JPY", rowVersion = 2)
        val original = pendingBudget().let { it.copy(row = it.row.copy(status = PendingMutationStatus.Done,
            lastError = "budget_read_refresh_required", receiptJson = "{\"row_version\":2}"), receipt = accepted) }
        owner.monthlyBudgetResponder = { Result.failure(java.io.IOException("Local read recovery unavailable")) }
        owner.commands.saves.value = listOf(original)
        advanceUntilIdle()
        assertNull(editor.uiState.value.budget)
        assertFalse(editor.uiState.value.hasPendingSave)

        owner.monthlyBudgetResponder = { Result.success(accepted) }
        editor.recoverSave(original, false)
        advanceUntilIdle()

        assertEquals(accepted, editor.uiState.value.budget)
        assertNull(editor.uiState.value.loadError)
        assertEquals(draft, editor.uiState.value.form)
        assertTrue(editor.uiState.value.formDirty)
        assertEquals(listOf(original), owner.commands.saves.value)
        assertEquals(0, owner.commands.savedRequests.size)
    }

    @Test fun doneBeforeEnqueueReturnsStillReadsTheAcceptedBudgetOnceSavingEnds() = budgetTest {
        val owner = FakeBudgetActions(budget = budget().copy(homeCurrencyCode = "JPY", nonMonthlyAmountCents = 0))
        val enqueueStarted = CompletableDeferred<Unit>()
        val returnEnqueue = CompletableDeferred<Result<Long>>()
        owner.commands.saveResponder = {
            enqueueStarted.complete(Unit)
            returnEnqueue.await()
        }
        val editor = BudgetViewModel(owner, "2026-05")
        advanceUntilIdle()
        editor.updateTotalAmount("1200")
        editor.save()
        advanceUntilIdle()
        assertTrue(enqueueStarted.isCompleted)
        assertTrue(editor.uiState.value.saving)
        val accepted = budget(totalAmountCents = 1200).copy(homeCurrencyCode = "JPY", nonMonthlyAmountCents = 0, rowVersion = 2)
        val original = pendingBudget().let { it.copy(row = it.row.copy(status = PendingMutationStatus.Done), receipt = accepted) }
        owner.budget = accepted
        owner.commands.saves.value = listOf(original)
        advanceUntilIdle()
        assertTrue(editor.uiState.value.saving, "Queue delivery must be observable before enqueue returns")
        assertNull(editor.uiState.value.budget, "The receipt must retire v1 without becoming a query")
        assertEquals(1, owner.loadCalls)

        returnEnqueue.complete(Result.success(original.row.id))
        advanceUntilIdle()

        assertFalse(editor.uiState.value.saving)
        assertEquals(accepted, editor.uiState.value.budget,
            "Done observed during saving must trigger the authoritative GET after enqueue returns")
        assertEquals(owner.readFetchedAt, editor.uiState.value.fetchedAt)
        assertEquals(2, owner.loadCalls)
        assertEquals(2L, editor.uiState.value.form.expectedRowVersion)
        assertFalse(editor.uiState.value.formDirty)
        assertEquals(listOf(original), owner.commands.saves.value)
        assertEquals(1, owner.commands.savedRequests.size)
    }

    private fun pendingBudget() = PendingBudgetSave(
        row = OutboxRow(id = 1, serverUrl = "https://api.example.com", ledgerId = "owner",
            type = PendingMutationType.SaveMonthlyBudget, targetId = "monthly_budget:2026-05", payloadJson = "{}",
            expectedRowVersion = 1, status = PendingMutationStatus.Pending, retryCount = 0, lastError = null,
            createdAt = "2026-05-01T00:00:00Z", attemptedAt = null, completedAt = null, idempotencyKey = "budget-original"),
        intent = BudgetSavePayload(1, "2026-05", "UTC", BudgetMonthlyUpdateRequestDto("JPY", null, 1200)),
        receipt = null,
    )
}
