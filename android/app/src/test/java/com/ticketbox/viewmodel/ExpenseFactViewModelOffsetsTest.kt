package com.ticketbox.viewmodel

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
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import org.junit.Test

/**
 * Refund/Chargeback/Reversal 纵向片：事实详情 offsets VM 最小 Gate Map。
 * 只保留能改变本片裁决的反例：登记成功且金额快照不构成客户端 eligibility、
 * bundle 不可读仍可提交合法 command、direct 409 的禁用/恢复、queued 不造幻影
 * 事实、void 全流程。金额上限永远由服务端 OCC + money owner 终裁。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactViewModelOffsetsTest : ExpenseFactViewModelTestBase() {

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
    fun `create success adopts bundle and amount above remaining snapshot is sent`() = edit { fake ->
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
            Result.success(ExpenseOffsetMutationOutcome.Synced(refunded, refreshPending = false))
        }
        vm.submitOffset()
        advanceUntilIdle()
        assertEquals(1, fake.createOffsetCalls)
        assertEquals(500L, fake.lastOffsetDraft?.originalAmountMinor)
        assertEquals(StreamOffsetKind.Refund, fake.lastOffsetDraft?.kind)
        assertEquals("商家退货", fake.lastOffsetDraft?.reason)
        val state = vm.uiState.value
        assertFalse(state.offsetForm.open)
        assertEquals(refunded, state.factBundle)
        assertEquals(2L, state.expense?.rowVersion)
        assertTrue(state.doneAdviceInputsChanged)
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
                ExpenseOffsetMutationOutcome.Synced(bundleOf(fake.baseExpense), false),
            )
        }
        vm.submitOffset()
        advanceUntilIdle()
        assertEquals(1, fake.createOffsetCalls)
        assertEquals(500L, fake.lastOffsetDraft?.originalAmountMinor)
        assertNotNull(vm.uiState.value.factBundle)
    }

    @Test
    fun `conflict blocks stale-token resubmit until authoritative refresh adopts`() = edit { fake ->
        fake.stubBundle()
        val vm = viewModel(fake)
        advanceUntilIdle()
        vm.openOffsetSheet(StreamOffsetKind.Refund)
        vm.updateOffsetFormField(OffsetFormField.Reason, "商家退货")
        // 第一轮：direct 409 且权威刷新失败 —— 旧 token 禁用、草稿保留、可重试失败态。
        fake.factBundleResult = {
            Result.failure(RepositoryException(errorCode = "server_unavailable", message = "down"))
        }
        fake.createOffsetResult = { _, _ ->
            Result.failure(RepositoryException(errorCode = "state_conflict", message = "conflict"))
        }
        vm.submitOffset()
        advanceUntilIdle()
        val blocked = vm.uiState.value.offsetForm
        assertTrue(blocked.open)
        assertEquals("商家退货", blocked.reason)
        assertNotNull(blocked.conflictMessage)
        assertTrue(blocked.refreshingAfterConflict)
        assertFalse(vm.canSubmitOffset())
        assertEquals(ExpenseDetailDataLoadState.Failed, vm.uiState.value.factBundleLoadState)
        // 第二轮：显式 retry，刷新成功 —— 整包采用 rv=2、解除禁用、草稿仍在。
        fake.factBundleResult = { Result.success(bundleOf(fake.baseExpense.copy(rowVersion = 2L))) }
        vm.loadExpenseFactBundle()
        advanceUntilIdle()
        val refreshed = vm.uiState.value.offsetForm
        assertFalse(refreshed.refreshingAfterConflict)
        assertEquals("商家退货", refreshed.reason)
        assertEquals(2L, vm.uiState.value.expense?.rowVersion)
        assertTrue(vm.canSubmitOffset())
    }

    @Test
    fun `queued outcome leaves session pending chip without phantom fact`() = edit { fake ->
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
        assertNotNull(state.pendingOffsetIntent)
        // queued 不冒充事实：activeOffsets 不变。
        assertTrue(state.factBundle?.activeOffsets?.isEmpty() == true)
    }

    @Test
    fun `void requires reason and applies returned bundle`() = edit { fake ->
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
                ExpenseOffsetMutationOutcome.Synced(
                    bundleOf(fake.baseExpense.copy(rowVersion = 2L), remaining = 1000L),
                    refreshPending = false,
                ),
            )
        }
        vm.submitVoidOffset()
        advanceUntilIdle()
        assertEquals(1, fake.voidOffsetCalls)
        assertEquals(offset, fake.lastVoidOffset)
        assertEquals("退款被收回", fake.lastVoidReason)
        assertFalse(vm.uiState.value.voidOffsetForm.open)
        assertEquals(2L, vm.uiState.value.expense?.rowVersion)
    }
}
