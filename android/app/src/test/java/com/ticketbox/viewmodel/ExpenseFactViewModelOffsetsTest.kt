package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseFinancialSummary
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.ExpenseOffsetIntentKind
import com.ticketbox.domain.model.ExpenseOffsetMutationOutcome
import com.ticketbox.domain.model.ExpenseOffsetStatus
import com.ticketbox.domain.model.ExpenseRelationshipImpacts
import com.ticketbox.domain.model.PendingExpenseOffsetIntent
import com.ticketbox.domain.model.StreamOffsetKind
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.job
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import org.junit.Test

/**
 * Refund/Chargeback/Reversal 纵向片：事实详情 offsets VM 最小 Gate Map。
 * 本地入队不冒充财务完成，只有权威 bundle 读取更新事实。
 * 金额上限由服务端 OCC + money owner 终裁；本地保存失败保留原填写。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactViewModelOffsetsTest : ExpenseFactViewModelTestBase() {

    @Test
    fun deliveredCurrencyCorrectionCannotReinterpretAnOpenRefundDraft() = edit { fake ->
        val vm = viewModel(fake)
        try {
            vm.openOffsetSheet(StreamOffsetKind.Refund)
            vm.updateOffsetFormField(OffsetFormField.Amount, "10.00")
            vm.updateOffsetFormField(OffsetFormField.Reason, "Original CNY refund")
            val original = vm.uiState.value.offsetForm
            fake.submitCorrection(fake.correctionBinding, fake.baseExpense,
                ExpenseCorrectionDraft("The receipt is in yen", originalCurrencyCode = CurrencyCode.JPY,
                    originalAmountMinor = 1_000L)).getOrThrow()
            advanceUntilIdle()
            fake.baseExpense = fake.baseExpense.copy(rowVersion = 2, factRevision = 2,
                originalCurrencyCode = CurrencyCode.JPY, originalCurrencyCodeRaw = "JPY", originalAmountMinor = 1_000L)
            fake.settleCorrection(com.ticketbox.data.local.PendingMutationStatus.Done)
            advanceUntilIdle()
            assertTrue(vm.uiState.value.authoritativeRootReady)
            assertEquals(CurrencyCode.JPY, vm.uiState.value.expense?.originalCurrencyCode)
            assertEquals(original.amountText, vm.uiState.value.offsetForm.amountText)

            assertFalse(vm.canSubmitOffset(), "adopting the root does not reinterpret the open CNY input as yen")
            vm.submitOffset()
            advanceUntilIdle()
            assertEquals(0, fake.createOffsetCalls)
            assertEquals(original.amountText, vm.uiState.value.offsetForm.amountText)
            vm.reviewOffsetDraft()
            assertEquals("", vm.uiState.value.offsetForm.amountText)
            assertEquals(original.reason, vm.uiState.value.offsetForm.reason)
            assertEquals(original.accountingDate, vm.uiState.value.offsetForm.accountingDate)
            vm.updateOffsetFormField(OffsetFormField.Amount, "10")
            assertTrue(vm.canSubmitOffset())
            vm.submitOffset()
            advanceUntilIdle()
            assertEquals(1, fake.createOffsetCalls)
            assertEquals(10L, fake.lastOffsetDraft?.originalAmountMinor)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun `correction blocks new offsets without discarding the already open draft`() = edit { fake ->
        val vm = viewModel(fake)
        try {
            vm.openOffsetSheet(StreamOffsetKind.Refund)
            vm.updateOffsetFormField(OffsetFormField.Amount, "10.00")
            vm.updateOffsetFormField(OffsetFormField.Reason, "Refund agreed in the original currency")
            val originalForm = vm.uiState.value.offsetForm
            assertTrue(originalForm.open)
            fake.submitCorrection(fake.correctionBinding, fake.baseExpense,
                ExpenseCorrectionDraft("The receipt is in yen", originalCurrencyCode = CurrencyCode.JPY,
                    originalAmountMinor = 1_000L)).getOrThrow()
            advanceUntilIdle()
            val original = vm.uiState.value.corrections.single()
            assertEquals("JPY", original.intent?.request?.originalCurrencyCode)
            assertEquals(CurrencyCode.CNY, vm.uiState.value.expense?.originalCurrencyCode)

            assertFalse(vm.canSubmitOffset())
            vm.submitOffset()
            advanceUntilIdle()
            assertEquals(0, fake.createOffsetCalls)
            assertEquals(originalForm, vm.uiState.value.offsetForm)
            vm.closeOffsetSheet()
            for (kind in listOf(StreamOffsetKind.Refund, StreamOffsetKind.Chargeback, StreamOffsetKind.Reversal)) {
                vm.openOffsetSheet(kind)
                assertFalse(vm.uiState.value.offsetForm.open)
            }
            assertEquals(original, vm.uiState.value.corrections.single())
            assertEquals(1, fake.correctCalls)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    private fun bundleOf(
        root: Expense,
        remaining: Long = 1000L,
        status: ExpenseLineageStatus = ExpenseLineageStatus.Confirmed,
        activeOffsets: List<ExpenseOffsetFact> = emptyList(),
    ): ExpenseFactBundle = ExpenseFactBundle(
        root = root,
        financialSummary = ExpenseFinancialSummary(
            grossOriginalMinor = root.originalAmountMinor ?: 0L,
            grossHomeAmountCents = root.amountCents ?: 0L,
            rootStreamAmountCents = root.amountCents ?: 0L,
            activeRefundedOriginalMinor = (root.originalAmountMinor ?: 0L) - remaining,
            remainingRefundableOriginalMinor = remaining,
            lineageHomeNetCents = root.amountCents ?: 0L,
            fxDifferenceCents = 0L,
            status = status,
        ),
        activeOffsets = activeOffsets,
        recentHistory = emptyList(),
        relationshipImpacts = ExpenseRelationshipImpacts(
            pendingInvitesCancelled = emptyList(),
            acceptedImpacts = emptyList(),
        ),
    )

    private fun offsetFact(publicId: String = "off-1"): ExpenseOffsetFact = ExpenseOffsetFact(
        publicId = publicId,
        kind = StreamOffsetKind.Refund,
        status = ExpenseOffsetStatus.Active,
        originalCurrencyCode = "CNY",
        originalAmountMinor = 500L,
        homeCurrencyCode = "CNY",
        amountCents = 500L,
        streamAmountCents = -500L,
        accountingDate = "2026-08-29",
        category = "餐饮",
        reason = "商家退货",
        rowVersion = 1L,
        factRevision = 1L,
        createdAt = "2026-08-29T10:00:00Z",
        updatedAt = "2026-08-29T10:00:00Z",
    )

    private fun FakeExpenseFactActions.stubBundle(bundle: ExpenseFactBundle = bundleOf(baseExpense)) {
        factBundleResult = { Result.success(bundle) }
    }

    @Test
    fun `create enqueues amount above snapshot then explicit read adopts accepted fact`() = edit { fake ->
        // remaining=100 minor（预填 1.00）；用户改输 5.00 超出快照 —— 快照只预填/提示，
        // 不是 eligibility Owner，command 必须照常到达 repository。
        fake.stubBundle(bundleOf(fake.baseExpense, remaining = 100L))
        val vm = viewModel(fake)
        advanceUntilIdle()
        vm.openOffsetSheet(StreamOffsetKind.Refund)
        assertEquals("1.00", vm.uiState.value.offsetForm.amountText)
        vm.updateOffsetFormField(OffsetFormField.Amount, "5.00")
        vm.updateOffsetFormField(OffsetFormField.Reason, "商家退货")
        val refunded = bundleOf(
            fake.baseExpense.copy(rowVersion = 2L),
            remaining = 0L,
            status = ExpenseLineageStatus.FullyRefunded,
            activeOffsets = listOf(offsetFact()),
        )
        fake.createOffsetResult = { _, _ ->
            Result.success(queued())
        }
        vm.submitOffset()
        advanceUntilIdle()
        assertEquals(1, fake.createOffsetCalls)
        assertEquals(500L, fake.lastOffsetDraft?.originalAmountMinor)
        assertEquals(StreamOffsetKind.Refund, fake.lastOffsetDraft?.kind)
        assertEquals("商家退货", fake.lastOffsetDraft?.reason)
        val state = vm.uiState.value
        assertFalse(state.offsetForm.open)
        assertEquals(1L, state.expense?.rowVersion)
        assertTrue(state.factBundle?.activeOffsets?.isEmpty() == true)
        assertFalse(state.doneAdviceInputsChanged)
        fake.stubBundle(refunded)
        vm.loadExpenseFactBundle()
        advanceUntilIdle()
        assertEquals(refunded, vm.uiState.value.factBundle)
        assertEquals(2L, vm.uiState.value.expense?.rowVersion)
    }

    @Test
    fun `create stays available when bundle read failed`() = edit { fake ->
        // factBundleResult 默认失败 → 等首读结算到 Failed，证明 command 不依赖 read model。
        val vm = viewModel(fake)
        advanceUntilIdle()
        assertNull(vm.uiState.value.factBundle)
        assertEquals(ExpenseDetailDataLoadState.Failed, vm.uiState.value.factBundleLoadState)
        vm.openOffsetSheet(StreamOffsetKind.Refund)
        assertTrue(vm.uiState.value.offsetForm.open)
        assertEquals("", vm.uiState.value.offsetForm.amountText)
        vm.updateOffsetFormField(OffsetFormField.Amount, "5.00")
        vm.updateOffsetFormField(OffsetFormField.Reason, "商家退货")
        fake.createOffsetResult = { _, _ ->
            Result.success(
                queued(),
            )
        }
        vm.submitOffset()
        advanceUntilIdle()
        assertEquals(1, fake.createOffsetCalls)
        assertEquals(500L, fake.lastOffsetDraft?.originalAmountMinor)
        assertNull(vm.uiState.value.factBundle)
        assertFalse(vm.uiState.value.doneAdviceInputsChanged)
    }

    @Test
    fun `local enqueue failures preserve both original forms without a server refresh`() = edit { fake ->
        val offset = offsetFact()
        val originalBundle = bundleOf(fake.baseExpense, remaining = 500L, activeOffsets = listOf(offset))
        var reads = 0
        fake.factBundleResult = { reads += 1; Result.success(originalBundle) }
        val vm = viewModel(fake)
        advanceUntilIdle()
        val readsBefore = reads
        vm.openOffsetSheet(StreamOffsetKind.Refund)
        vm.updateOffsetFormField(OffsetFormField.Amount, "3.00")
        vm.updateOffsetFormField(OffsetFormField.Reason, "Original refund")
        val original = vm.uiState.value.offsetForm
        fake.createOffsetResult = { _, _ -> Result.failure(RepositoryException("Local storage unavailable")) }

        vm.submitOffset()
        advanceUntilIdle()
        val rejected = vm.uiState.value.offsetForm
        assertTrue(rejected.open)
        assertFalse(rejected.saving)
        assertEquals(original.sourceExpense, rejected.sourceExpense)
        assertEquals(original.amountText, rejected.amountText)
        assertEquals(original.accountingDate, rejected.accountingDate)
        assertEquals(original.reason, rejected.reason)
        assertNotNull(rejected.submitError)
        assertEquals(originalBundle, vm.uiState.value.factBundle)
        assertEquals(readsBefore, reads)

        vm.closeOffsetSheet()
        vm.openVoidOffsetSheet(offset)
        vm.updateVoidOffsetReason("Original void")
        fake.voidOffsetResult = { _, _, _ -> Result.failure(RepositoryException("Local storage unavailable")) }
        vm.submitVoidOffset()
        advanceUntilIdle()
        assertTrue(vm.uiState.value.voidOffsetForm.open)
        assertEquals("Original void", vm.uiState.value.voidOffsetForm.reason)
        assertNotNull(vm.uiState.value.voidOffsetForm.submitError)
        assertEquals(offset, fake.lastVoidOffset)
        assertEquals(originalBundle, vm.uiState.value.factBundle)
        assertEquals(readsBefore, reads)
    }

    @Test
    fun `queued outcome acknowledges saved intent without changing financial facts`() = edit { fake ->
        fake.stubBundle()
        val vm = viewModel(fake)
        advanceUntilIdle()
        vm.openOffsetSheet(StreamOffsetKind.Refund)
        vm.updateOffsetFormField(OffsetFormField.Reason, "商家退货")
        fake.createOffsetResult = { _, _ ->
            Result.success(
                ExpenseOffsetMutationOutcome.Queued(
                    PendingExpenseOffsetIntent(
                        operation = ExpenseOffsetIntentKind.Create,
                        offsetKind = StreamOffsetKind.Refund,
                        offsetPublicId = null,
                        reason = "商家退货",
                    ),
                ),
            )
        }
        vm.submitOffset()
        advanceUntilIdle()
        val state = vm.uiState.value
        assertFalse(state.offsetForm.open)
        assertNotNull(state.message)
        assertFalse(state.doneAdviceInputsChanged)
        // The durable Outbox owns pending intent; this screen acknowledges saving only.
        assertTrue(state.factBundle?.activeOffsets?.isEmpty() == true)
    }

    @Test
    fun `void requires reason and keeps the active fact until explicit accepted read`() = edit { fake ->
        val offset = offsetFact()
        fake.stubBundle(bundleOf(fake.baseExpense, remaining = 500L, activeOffsets = listOf(offset)))
        val vm = viewModel(fake)
        advanceUntilIdle()
        vm.openVoidOffsetSheet(offset)
        assertFalse(vm.canSubmitVoidOffset())
        vm.updateVoidOffsetReason("退款被收回")
        assertTrue(vm.canSubmitVoidOffset())
        fake.voidOffsetResult = { _, _, _ ->
            Result.success(
                queued(ExpenseOffsetIntentKind.Void, offset.publicId),
            )
        }
        vm.submitVoidOffset()
        advanceUntilIdle()
        assertEquals(1, fake.voidOffsetCalls)
        assertEquals(offset, fake.lastVoidOffset)
        assertEquals("退款被收回", fake.lastVoidReason)
        assertFalse(vm.uiState.value.voidOffsetForm.open)
        assertEquals(listOf(offset), vm.uiState.value.factBundle?.activeOffsets)
        assertEquals(1L, vm.uiState.value.expense?.rowVersion)
        assertFalse(vm.uiState.value.doneAdviceInputsChanged)
        fake.stubBundle(bundleOf(fake.baseExpense.copy(rowVersion = 2L), remaining = 1000L))
        vm.loadExpenseFactBundle()
        advanceUntilIdle()
        assertTrue(vm.uiState.value.factBundle?.activeOffsets?.isEmpty() == true)
        assertEquals(2L, vm.uiState.value.expense?.rowVersion)
    }

    private fun queued(operation: ExpenseOffsetIntentKind = ExpenseOffsetIntentKind.Create, publicId: String? = null) =
        ExpenseOffsetMutationOutcome.Queued(PendingExpenseOffsetIntent(operation, StreamOffsetKind.Refund, publicId, "商家退货"))
}
