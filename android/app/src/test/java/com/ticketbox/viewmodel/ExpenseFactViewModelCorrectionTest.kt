package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle

/** A1: 更正草稿只发送用户真正改变且有权修改的事实。 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactViewModelCorrectionTest : ExpenseFactViewModelTestBase() {

    @Test
    fun `blank reason blocks the draft locally and never reaches the repository`() = edit { fake ->
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "   ")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "新商家")

        vm.submitCorrection()
        advanceUntilIdle()

        assertEquals(
            R.string.expense_correction_reason_required,
            (vm.uiState.value.correction.submitError as? UiText.Res)?.id,
        )
        assertNull(vm.uiState.value.message)
        assertEquals(0, fake.correctCalls, "reason 空白不得发出更正请求")
        assertTrue(vm.uiState.value.correction.open, "本地拦截后表单保持打开")
    }

    @Test
    fun `zero changes against baseline is rejected as no_changes`() = edit { fake ->
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "小票金额看错了")

        vm.submitCorrection()
        advanceUntilIdle()

        assertEquals(
            R.string.expense_correction_no_changes,
            (vm.uiState.value.correction.submitError as? UiText.Res)?.id,
        )
        assertEquals(0, fake.correctCalls)
    }

    @Test
    fun `merchant-only diff carries only merchant and reason`() = edit { fake ->
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "小票金额看错了")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "青禾小馆·静安店")

        vm.submitCorrection()
        advanceUntilIdle()

        val draft = assertNotNull(fake.lastCorrectionDraft)
        assertEquals("小票金额看错了", draft.reason)
        assertEquals("青禾小馆·静安店", draft.merchant)
        assertNull(draft.originalAmountMinor)
        assertNull(draft.category)
        assertNull(draft.note)
        assertNull(draft.tags)
        assertNull(draft.expenseTime)
        assertNull(draft.items)
        assertNull(draft.splits)
    }

    @Test
    fun `read-only ledger cannot open the correction sheet`() = edit { fake ->
        fake.canModifyLedgerFlag = false
        val vm = viewModel(fake)

        vm.openCorrectionSheet()

        assertFalse(vm.uiState.value.correction.open, "只读账本不得打开更正表单")
        assertEquals(R.string.expense_correction_readonly_blocked, (vm.uiState.value.message as? UiText.Res)?.id)
        assertEquals(0, fake.correctCalls)
    }

    @Test
    fun `merchant time and scores preserve explicit clear intent`() = edit { fake ->
        fake.baseExpense = fake.baseExpense.copy(
            merchant = "应清空",
            expenseTime = "2026-05-04T00:30:00Z",
            valueScore = 5,
            regretScore = 2,
        )
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "移除错误附加事实")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "")
        vm.updateCorrectionField(CorrectionScalarField.ExpenseTime, "")
        vm.updateCorrectionScore(CorrectionScoreField.Value, null)
        vm.updateCorrectionScore(CorrectionScoreField.Regret, null)

        vm.submitCorrection()
        advanceUntilIdle()

        val draft = assertNotNull(fake.lastCorrectionDraft)
        assertEquals("", draft.merchant)
        assertTrue(draft.expenseTimeChanged)
        assertNull(draft.expenseTime)
        assertTrue(draft.valueScoreChanged)
        assertNull(draft.valueScore)
        assertTrue(draft.regretScoreChanged)
        assertNull(draft.regretScore)
    }

    @Test
    fun `unknown original currency does not block a non-amount correction`() = edit { fake ->
        fake.baseExpense = fake.baseExpense.copy(
            originalCurrencyCodeRaw = "VND",
            originalAmountMinor = 1200L,
        )
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "商家识别错了")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "正确商家")

        vm.submitCorrection()
        advanceUntilIdle()

        val draft = assertNotNull(fake.lastCorrectionDraft)
        assertEquals("正确商家", draft.merchant)
        assertNull(draft.originalCurrencyCode)
        assertNull(draft.originalAmountMinor)
    }

    @Test
    fun `server over-allocation stays visible inside the sheet until the user edits`() = edit { fake ->
        fake.correctResult = { _, _ ->
            Result.failure(
                RepositoryException(
                    errorCode = "expense_split_total_exceeds_parent",
                    message = "server copy must not own Android UI",
                ),
            )
        }
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "金额应更低")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "新商家")

        vm.submitCorrection()
        advanceUntilIdle()

        val failed = vm.uiState.value
        assertTrue(failed.correction.open)
        assertEquals("新商家", failed.correction.merchant)
        assertEquals(
            R.string.error_expense_split_total_exceeds_parent,
            (failed.correction.submitError as? UiText.Res)?.id,
        )
        assertNull(failed.message, "弹层错误不得藏到弹层后的页级 banner")

        vm.updateCorrectionField(CorrectionScalarField.Merchant, "再次调整")
        assertNull(vm.uiState.value.correction.submitError)
    }
}
