package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.ExpenseItem
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.ItemsSumStatus
import com.ticketbox.domain.model.MessageTone
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle

/** A1: 更正结果忠实呈现同步、离线排队和 OCC 冲突的权威状态。 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactViewModelCorrectionOutcomeTest : ExpenseFactViewModelTestBase() {

    @Test
    fun `accepted correction leaves facts unchanged then DONE reloads authoritative expense and timeline`() = edit { fake ->
        val vm = viewModel(fake)
        val revisionsBefore = fake.fetchRevisionsCalls
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "小票金额看错了")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "新商家")

        vm.submitCorrection()
        advanceUntilIdle()

        assertFalse(vm.uiState.value.correction.open)
        assertEquals("旧商家", vm.uiState.value.expense?.merchant)
        assertEquals(revisionsBefore, fake.fetchRevisionsCalls)
        fake.baseExpense = fake.baseExpense.copy(merchant = "新商家", rowVersion = 2, factRevision = 2)
        fake.settleCorrection(PendingMutationStatus.Done)
        advanceUntilIdle()
        assertEquals("新商家", vm.uiState.value.expense?.merchant)
        assertTrue(vm.uiState.value.corrections.single().delivered)
        assertEquals(revisionsBefore + 1, fake.fetchRevisionsCalls, "Synced 后重拉时间线（不本地伪造 revision）")
        assertFalse(vm.uiState.value.doneAdviceInputsChanged, "仅商家变化不应失效建议缓存")
    }

    @Test
    fun `fresh confirmed snapshot does not trigger a duplicate expense fetch`() = edit { fake ->
        val vm = ExpenseFactViewModel(
            expenseId = fake.baseExpense.id,
            repository = fake,
            initialExpense = fake.baseExpense,
        )
        advanceUntilIdle()

        assertEquals(fake.baseExpense, vm.uiState.value.expense)
        assertEquals(0, fake.fetchExpenseCalls)
        assertEquals(1, fake.fetchBillSplitSentCalls)
        assertEquals(ExpenseDetailDataLoadState.Loaded, vm.uiState.value.expenseLoadState)
    }

    @Test
    fun `category correction invalidates advice inputs`() = edit { fake ->
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "分类识别错了")
        vm.updateCorrectionField(CorrectionScalarField.Category, "居家")

        vm.submitCorrection()
        advanceUntilIdle()

        assertTrue(vm.uiState.value.doneAdviceInputsChanged)
    }

    @Test
    fun `queued correction exposes original input without overwriting the authoritative expense`() = edit { fake ->
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "小票金额看错了")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "新商家")

        vm.submitCorrection()
        advanceUntilIdle()

        assertFalse(vm.uiState.value.correction.open)
        assertEquals("旧商家", vm.uiState.value.expense?.merchant)
        assertEquals("新商家", vm.uiState.value.corrections.single().intent?.request?.merchant)
        assertEquals(PendingMutationStatus.Pending, vm.uiState.value.corrections.single().row.status)
        assertEquals(MessageTone.Info, vm.uiState.value.messageTone)
    }

    @Test
    fun `queued home-currency amount correction keeps the amount and allocation projection consistent`() = edit { fake ->
        fake.splitsResult = Result.success(
            ExpenseSplits(
                expenseId = fake.baseExpense.id,
                parentAmountCents = 1_000L,
                splitsTotalAmountCents = 1_000L,
                mismatchCents = 0L,
                splits = emptyList(),
            ),
        )
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "金额应更高")
        vm.updateCorrectionField(CorrectionScalarField.Amount, "12.00")

        vm.submitCorrection()
        advanceUntilIdle()

        assertEquals(1_000L, vm.uiState.value.expense?.amountCents)
        assertEquals(1_000L, vm.uiState.value.expenseSplits?.parentAmountCents)
        assertEquals(1_000L, vm.uiState.value.expenseSplits?.splitsTotalAmountCents)
        assertEquals(0L, vm.uiState.value.expenseSplits?.mismatchCents)
        assertEquals(1_200L, vm.uiState.value.corrections.single().intent?.request?.originalAmountMinor)
    }

    @Test
    fun `queued amount correction reconciles the loaded item summary`() = edit { fake ->
        fake.itemsResult = Result.success(
            ExpenseItems(
                expenseId = fake.baseExpense.id,
                parentAmountCents = 1_000L,
                itemsTotalAmountCents = 1_000L,
                mismatchCents = 0L,
                itemsSumStatus = ItemsSumStatus.MATCHED,
                items = listOf(
                    ExpenseItem(
                        publicId = "item-1",
                        position = 0,
                        name = "商品",
                        quantityText = null,
                        unitPriceCents = null,
                        amountCents = 1_000L,
                        category = "其他",
                        rawText = null,
                        confidence = null,
                        isOcrDraft = false,
                        createdAt = "",
                        updatedAt = "",
                    ),
                ),
            ),
        )
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "金额应更高")
        vm.updateCorrectionField(CorrectionScalarField.Amount, "12.00")

        vm.submitCorrection()
        advanceUntilIdle()

        assertEquals(1_000L, vm.uiState.value.expense?.amountCents)
        assertEquals(1_000L, vm.uiState.value.expenseItems?.parentAmountCents)
        assertEquals(1_000L, vm.uiState.value.expenseItems?.itemsTotalAmountCents)
        // Pending input is not an authoritative parent/collection replacement.
        assertEquals(0L, vm.uiState.value.expenseItems?.mismatchCents)
        assertEquals(1_200L, vm.uiState.value.corrections.single().intent?.request?.originalAmountMinor)
        assertEquals(ItemsSumStatus.MATCHED, vm.uiState.value.expenseItems?.itemsSumStatus)
    }

    @Test
    fun `durable conflict preserves original submission and requires review instead of a new token`() = edit { fake ->
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "原更正")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "我手里的旧值")
        vm.submitCorrection()
        advanceUntilIdle()
        val original = vm.uiState.value.corrections.single()
        fake.settleCorrection(PendingMutationStatus.Conflict)
        advanceUntilIdle()
        val conflict = vm.uiState.value.corrections.single()
        assertEquals(original.intent, conflict.intent)
        assertEquals(original.row.idempotencyKey, conflict.row.idempotencyKey)
        assertFalse(conflict.canRetry)
        assertTrue(conflict.canDiscard)
        vm.openCorrectionSheet()
        assertFalse(vm.uiState.value.correction.open)
    }

    @Test
    fun `delivery remains visible through failed reads and screen recreation`() = edit { fake ->
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "金额")
        vm.updateCorrectionField(CorrectionScalarField.Amount, "12.00")
        vm.submitCorrection()
        advanceUntilIdle()
        fake.fetchExpenseFailure = RepositoryException("offline")
        fake.settleCorrection(PendingMutationStatus.Done)
        advanceUntilIdle()
        assertTrue(vm.uiState.value.corrections.single().delivered)
        assertEquals(1_000L, vm.uiState.value.expense?.amountCents)
        assertTrue(vm.uiState.value.expenseStale)
        val reopened = viewModel(fake)
        assertTrue(reopened.uiState.value.corrections.single().delivered)
        assertEquals(ExpenseDetailDataLoadState.Failed, reopened.uiState.value.expenseLoadState)
        fake.fetchExpenseFailure = null
        fake.baseExpense = fake.baseExpense.copy(amountCents = 1200, rowVersion = 2, factRevision = 2)
        reopened.refreshCorrectionFact()
        advanceUntilIdle()
        assertEquals(1_200L, reopened.uiState.value.expense?.amountCents)
        assertTrue(reopened.uiState.value.corrections.single().delivered)
        assertEquals(1, fake.correctCalls, "read recovery cannot resubmit")
    }
}
