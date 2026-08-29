package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.projectCorrection
import com.ticketbox.domain.model.ExpenseCorrectionOutcome
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
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
    fun `synced correction closes the sheet, applies the authoritative expense and reloads the timeline`() = edit { fake ->
        val vm = viewModel(fake)
        val revisionsBefore = fake.fetchRevisionsCalls
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "小票金额看错了")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "新商家")

        vm.submitCorrection()
        advanceUntilIdle()

        assertFalse(vm.uiState.value.correction.open, "Synced 后 sheet 关闭")
        assertEquals("新商家", vm.uiState.value.expense?.merchant)
        assertEquals(R.string.expense_correction_saved, (vm.uiState.value.message as? UiText.Res)?.id)
        assertEquals(MessageTone.Success, vm.uiState.value.messageTone)
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
    fun `queued correction surfaces the offline hint with the optimistic expense`() = edit { fake ->
        fake.correctResult = { expense, _ ->
            Result.success(ExpenseCorrectionOutcome.Queued(expense = expense.copy(merchant = "新商家")))
        }
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "小票金额看错了")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "新商家")

        vm.submitCorrection()
        advanceUntilIdle()

        assertFalse(vm.uiState.value.correction.open)
        assertEquals("新商家", vm.uiState.value.expense?.merchant)
        assertEquals(R.string.expense_correction_queued, (vm.uiState.value.message as? UiText.Res)?.id)
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
        fake.correctResult = { expense, draft ->
            Result.success(ExpenseCorrectionOutcome.Queued(expense.projectCorrection(draft)))
        }
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "金额应更高")
        vm.updateCorrectionField(CorrectionScalarField.Amount, "12.00")

        vm.submitCorrection()
        advanceUntilIdle()

        assertEquals(1_200L, vm.uiState.value.expense?.amountCents)
        assertEquals(1_200L, vm.uiState.value.expenseSplits?.parentAmountCents)
        assertEquals(1_000L, vm.uiState.value.expenseSplits?.splitsTotalAmountCents)
        assertEquals(200L, vm.uiState.value.expenseSplits?.mismatchCents)
    }

    @Test
    fun `direct state_conflict refreshes the authoritative fact and keeps the sheet open`() = edit { fake ->
        fake.correctResult = { _, _ ->
            Result.failure(RepositoryException(errorCode = "state_conflict", message = "conflict"))
        }
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "小票金额看错了")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "我手里的旧值")

        val fetchesBefore = fake.fetchExpenseCalls
        vm.submitCorrection()
        advanceUntilIdle()

        assertEquals(
            R.string.expense_correction_conflict,
            (vm.uiState.value.correction.conflictMessage as? UiText.Res)?.id,
        )
        assertTrue(vm.uiState.value.correction.open, "冲突后表单保持打开（提交值保留）")
        assertFalse(vm.uiState.value.correction.saving)
        assertTrue(fake.fetchExpenseCalls > fetchesBefore, "冲突后必须重取权威事实")
    }
}
