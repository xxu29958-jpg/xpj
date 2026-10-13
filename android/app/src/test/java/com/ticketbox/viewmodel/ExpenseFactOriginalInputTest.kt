package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.StreamOffsetKind
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.job
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactOriginalInputTest : ExpenseFactViewModelTestBase() {
    @Test
    fun changedReceiptLinesRequireAChoiceAndKeepCurrentHiddenProvenance() = edit { fake ->
        val item = com.ticketbox.domain.model.ExpenseItem(publicId = "line-1", position = 0, name = "原名称",
            quantityText = "原数量", unitPriceCents = 500, amountCents = 1000, category = "原分类",
            rawText = "original source", confidence = 0.5, isOcrDraft = false, createdAt = "", updatedAt = "")
        fake.itemsResult = fake.itemsResult.map { it.copy(items = listOf(item)) }
        val vm = viewModel(fake)
        try {
            vm.openCorrectionSheet()
            vm.updateCorrectionField(CorrectionScalarField.Reason, "核对明细")
            vm.openCorrectionItemsEditor()
            vm.updateCorrectionItemDraft(0, "我的名称", null, null)
            vm.adoptCorrectionItems()
            fake.baseExpense = fake.baseExpense.copy(rowVersion = 2)
            fake.itemsResult = fake.itemsResult.map { it.copy(parentRowVersion = 2,
                items = listOf(item.copy(quantityText = "后来人工数量", rawText = "later source", category = "后来分类"))) }
            vm.refreshCorrectionFact()
            advanceUntilIdle()
            assertTrue(vm.correctionReview()?.itemsChoiceRequired == true)
            vm.reviewCorrectionDraft(CorrectionReviewSelection(currentVersion = 2))
            assertEquals(1L, vm.correctionBaseline?.rowVersion)
            assertFalse(vm.canSubmitCorrection())
            vm.reviewCorrectionDraft(CorrectionReviewSelection(currentVersion = 2, keepItems = true))
            advanceUntilIdle()
            vm.submitCorrection()
            advanceUntilIdle()
            assertEquals(1, fake.correctCalls)
            val submitted = fake.lastCorrectionDraft?.items?.single()
            assertEquals("我的名称", submitted?.name)
            assertEquals("后来人工数量", submitted?.quantityText)
            assertEquals("later source", submitted?.rawText)
            assertEquals("后来分类", submitted?.category)
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    @Test
    fun failedLocalSaveBlocksExitAndCommandUntilTheOriginalCanBePersisted() = edit { fake ->
        var diskFailed = true
        val repository = object : com.ticketbox.data.repository.ExpenseFactActions by fake {
            override suspend fun saveFactInput(expected: com.ticketbox.data.repository.ExpenseFactOriginalInput?,
                input: com.ticketbox.data.repository.ExpenseFactOriginalInput): Result<Unit> =
                if (diskFailed) Result.failure(RepositoryException("磁盘暂不可写")) else fake.saveFactInput(expected, input)
        }
        val vm = ExpenseFactViewModel(7, repository)
        advanceUntilIdle()
        try {
            vm.openCorrectionSheet()
            vm.updateCorrectionField(CorrectionScalarField.Reason, "不能丢的原因")
            vm.updateCorrectionField(CorrectionScalarField.Merchant, "不能丢的商家")
            var left = false
            vm.leaveFactPage { left = true }
            advanceUntilIdle()
            assertFalse(left)
            assertTrue(vm.uiState.value.factInputError != null)
            vm.submitCorrection()
            advanceUntilIdle()
            assertEquals(0, fake.correctCalls)
            assertEquals("不能丢的商家", vm.uiState.value.correction.merchant)
            diskFailed = false
            vm.retryFactInputSave()
            advanceUntilIdle()
            assertEquals("不能丢的原因", ExpenseFactInputCodec.decode(fake.originalInputs.single().json, 7).correction?.reason)
            vm.leaveFactPage { left = true }
            advanceUntilIdle()
            assertTrue(left)
            assertTrue(vm.uiState.value.factInputError == null)
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    @Test
    fun explicitReviewKeepsMyRawMoneyAndUsesPeerEditsForUntouchedFields() = edit { fake ->
        val vm = viewModel(fake)
        try {
            vm.openCorrectionSheet()
            vm.updateCorrectionField(CorrectionScalarField.Reason, "原小票核对")
            vm.updateCorrectionField(CorrectionScalarField.Amount, " 12.50 ")
            vm.updateCorrectionField(CorrectionScalarField.Note, "我的原稿")
            advanceUntilIdle()
            val originalKey = fake.originalInputs.single().originalKey
            fake.baseExpense = fake.baseExpense.copy(rowVersion = 2, merchant = "另一端商家", category = "购物",
                tags = "peer", originalCurrencyCode = CurrencyCode.JPY, originalCurrencyCodeRaw = "JPY", originalAmountMinor = 1_000)
            vm.retryLoadExpense()
            advanceUntilIdle()
            assertFalse(vm.canSubmitCorrection())
            vm.reviewCorrectionDraft(CorrectionReviewSelection(currentVersion = 2))
            assertEquals(1L, vm.correctionBaseline?.rowVersion)
            assertEquals(originalKey, fake.originalInputs.single().originalKey)
            vm.reviewCorrectionDraft(CorrectionReviewSelection(currentVersion = 1, scalars = mapOf(CorrectionReviewField.Money to true)))
            assertEquals(1L, vm.correctionBaseline?.rowVersion)
            vm.reviewCorrectionDraft(CorrectionReviewSelection(currentVersion = 2, scalars = mapOf(CorrectionReviewField.Money to true)))
            advanceUntilIdle()
            assertEquals(" 12.50 ", vm.uiState.value.correction.amountText)
            assertEquals(CurrencyCode.CNY, vm.uiState.value.correction.currency)
            assertEquals("另一端商家", vm.uiState.value.correction.merchant)
            assertEquals("购物", vm.uiState.value.correction.category)
            assertEquals("peer", vm.uiState.value.correction.tags)
            assertEquals("我的原稿", vm.uiState.value.correction.note)
            assertTrue(fake.originalInputs.single().originalKey != originalKey)
            vm.submitCorrection()
            advanceUntilIdle()
            assertEquals(1, fake.correctCalls)
            assertTrue(fake.originalInputs.isEmpty())
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    @Test
    fun navigationFlushAndRecreatedViewModelKeepTheSameOriginalInput() = edit { fake ->
        val first = viewModel(fake)
        first.openCorrectionSheet()
        first.updateCorrectionField(CorrectionScalarField.Reason, "  复核  ")
        first.updateCorrectionField(CorrectionScalarField.Amount, "1.")
        first.updateCorrectionField(CorrectionScalarField.TimeForm, "{\"unfinished\":true}")
        var left = false
        first.leaveFactPage { left = true }
        advanceUntilIdle()
        assertTrue(left)
        val original = fake.originalInputs.single()
        first.viewModelScope.coroutineContext.job.cancelAndJoin()
        val reopened = viewModel(fake)
        try {
            assertTrue(reopened.uiState.value.factInputKeys.contains("correction"))
            reopened.openCorrectionSheet()
            assertEquals("  复核  ", reopened.uiState.value.correction.reason)
            assertEquals("1.", reopened.uiState.value.correction.amountText)
            assertEquals("{\"unfinished\":true}", reopened.uiState.value.correction.timeFormJson)
            assertEquals(original, fake.originalInputs.single())
            reopened.discardFactInput("correction")
            advanceUntilIdle()
            assertTrue(fake.originalInputs.isEmpty())
            assertFalse(reopened.uiState.value.correction.open)
            assertEquals(0, fake.correctCalls)
        } finally { reopened.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    @Test
    fun reopeningCorrectionKeepsTheOriginalInputAndCurrencyBasis() = edit { fake ->
        val vm = viewModel(fake)
        try {
            vm.openCorrectionSheet()
            vm.updateCorrectionField(CorrectionScalarField.Reason, "  核对原小票  ")
            vm.updateCorrectionField(CorrectionScalarField.Merchant, "原稿中的商家")
            vm.updateCorrectionField(CorrectionScalarField.Amount, " 0012.00 ")
            vm.updateCorrectionField(CorrectionScalarField.Note, "尚未提交的解释")
            val original = vm.uiState.value.correction
            val originalBasis = vm.correctionBaseline
            vm.closeCorrectionSheet()

            fake.baseExpense = fake.baseExpense.copy(rowVersion = 2, factRevision = 2,
                merchant = "另一端已核对", originalCurrencyCode = CurrencyCode.JPY,
                originalCurrencyCodeRaw = "JPY", originalAmountMinor = 1_000L)
            vm.retryLoadExpense()
            advanceUntilIdle()
            vm.openCorrectionSheet()

            assertEquals(original.reason, vm.uiState.value.correction.reason, "Closing the sheet is not discarding the original correction")
            assertEquals(original.merchant, vm.uiState.value.correction.merchant)
            assertEquals(original.amountText, vm.uiState.value.correction.amountText)
            assertEquals(original.note, vm.uiState.value.correction.note)
            assertEquals(original.currency, vm.uiState.value.correction.currency)
            assertEquals(originalBasis, vm.correctionBaseline, "Reopening must not reinterpret original money with the latest currency and OCC")
            assertFalse(vm.canSubmitCorrection())
            vm.submitCorrection()
            advanceUntilIdle()
            assertEquals(0, fake.correctCalls, "The original basis still needs an explicit review")
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun reopeningRefundAfterAReadFailureKeepsTheOriginalSubmissionValues() = edit { fake ->
        val vm = viewModel(fake)
        try {
            vm.openOffsetSheet(StreamOffsetKind.Refund)
            vm.updateOffsetFormField(OffsetFormField.Amount, " 0005.50 ")
            vm.updateOffsetFormField(OffsetFormField.AccountingDate, "2026-08-30")
            vm.updateOffsetFormField(OffsetFormField.Reason, "商家同意退回")
            val original = vm.uiState.value.offsetForm
            vm.closeOffsetSheet()
            fake.factBundleResult = { Result.failure(RepositoryException("Offline")) }
            vm.loadExpenseFactBundle()
            advanceUntilIdle()
            vm.openOffsetSheet(StreamOffsetKind.Refund)

            assertEquals(original.amountText, vm.uiState.value.offsetForm.amountText, "A failed read cannot replace the unfinished refund")
            assertEquals(original.accountingDate, vm.uiState.value.offsetForm.accountingDate)
            assertEquals(original.reason, vm.uiState.value.offsetForm.reason)
            assertEquals(original.sourceExpense, vm.uiState.value.offsetForm.sourceExpense)
            assertEquals(0, fake.createOffsetCalls)
            // Raw, unfinished text survives even when it is not yet a canonical money value.
            vm.submitOffset()
            advanceUntilIdle()
            assertEquals(0, fake.createOffsetCalls)
            assertEquals(original.amountText, vm.uiState.value.offsetForm.amountText)
            vm.updateOffsetFormField(OffsetFormField.Amount, "5.50")
            vm.submitOffset()
            advanceUntilIdle()
            assertEquals(1, fake.createOffsetCalls, "${vm.uiState.value.offsetForm.submitError}; ${vm.uiState.value.factInputError}")
            assertEquals(550L, fake.lastOffsetDraft?.originalAmountMinor)
            assertEquals("2026-08-30", fake.lastOffsetDraft?.accountingDate)
            assertEquals(original.reason, fake.lastOffsetDraft?.reason)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }
}
