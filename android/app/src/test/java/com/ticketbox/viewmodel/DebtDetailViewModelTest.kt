package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtDetailActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtRepaymentFact
import com.ticketbox.domain.model.DebtRepaymentFactStatuses
import com.ticketbox.domain.model.DebtRepaymentHistory
import com.ticketbox.domain.model.DebtRepaymentRecord
import com.ticketbox.domain.model.DebtRepaymentVoidFact
import com.ticketbox.domain.model.DebtSourceTypes
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DebtDetailViewModelTest {

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
    fun loadDebtPopulatesStateAndReflectsRole() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(
            canModify = false,
            getResult = Result.success(sampleDebt("d1", remaining = 4_200L)),
            historyResult = Result.success(repaymentHistory("d1")),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        assertEquals("d1", viewModel.state.value.debt?.publicId)
        assertEquals(4_200L, viewModel.state.value.debt?.remainingAmountCents)
        assertEquals(false, viewModel.state.value.canModify)
        assertEquals(false, viewModel.state.value.isLoading)
        assertEquals("repayment-1", viewModel.state.value.repaymentHistory?.items?.single()?.publicId)
        assertEquals(1, repo.historyCalls.size)
    }

    @Test
    fun loadDebtFailureSetsError() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(getResult = Result.failure(RuntimeException("offline")))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        assertNull(viewModel.state.value.debt)
        assertTrue(viewModel.state.value.error != null)
    }

    @Test
    fun repaymentHistoryFailureKeepsDebtDetailReadable() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(
            getResult = Result.success(sampleDebt("d1")),
            historyResult = Result.failure(RuntimeException("history offline")),
        )
        val viewModel = DebtDetailViewModel(repo)

        viewModel.loadDebt("d1")
        advanceUntilIdle()

        assertEquals("d1", viewModel.state.value.debt?.publicId)
        assertNull(viewModel.state.value.error)
        assertNull(viewModel.state.value.repaymentHistory)
        assertTrue(viewModel.state.value.repaymentHistoryError != null)
        assertEquals(false, viewModel.state.value.isRepaymentHistoryLoading)
    }

    @Test
    fun openActionSetsActiveActionAndClearsInputs() = runTest(dispatcher) {
        val viewModel = DebtDetailViewModel(FakeDebtDetailActions())
        viewModel.updateAmount("99")
        viewModel.openAction(DebtAction.Repayment)

        assertEquals(DebtAction.Repayment, viewModel.state.value.activeAction)
        assertEquals("", viewModel.state.value.amountInput)
        assertEquals(true, viewModel.state.value.adjustmentIncrease)
    }

    @Test
    fun submitRepaymentSendsOccAmountAndSwapsFold() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(
            getResult = Result.success(sampleDebt("d1", rowVersion = 5L, remaining = 50_000L)),
            writeResult = Result.success(sampleDebt("d1", rowVersion = 6L, remaining = 40_000L)),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()
        repo.historyResult = Result.success(repaymentHistory("d1", amountCents = 10_000L))

        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("100")
        viewModel.submit()
        advanceUntilIdle()

        val call = repo.repaymentCalls.single()
        assertEquals("d1", call.publicId)
        // OCC carrier = the loaded Debt's row_version.
        assertEquals(5L, call.expectedRowVersion)
        assertEquals(10_000L, call.amountCents)
        // Fold-after Debt swapped in (row_version advanced, remaining dropped); dialog closed + flash.
        assertEquals(6L, viewModel.state.value.debt?.rowVersion)
        assertEquals(40_000L, viewModel.state.value.debt?.remainingAmountCents)
        val repayment = viewModel.state.value.repaymentHistory?.items?.single()
        assertEquals("repayment-1", repayment?.publicId)
        assertEquals(10_000L, repayment?.amountCents)
        assertEquals(2, repo.historyCalls.size)
        assertNull(viewModel.state.value.activeAction)
        assertTrue(viewModel.state.value.flashMessage != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun submitRepaymentRejectsSurplusFractionalPrecisionWithoutWrite() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(
            getResult = Result.success(sampleDebt("d1", rowVersion = 1L, remaining = 50_000L)),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("1.005")
        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.repaymentCalls.isEmpty())
        assertEquals(DebtAction.Repayment, viewModel.state.value.activeAction)
    }

    @Test
    fun submitRepaymentValidationBlocksNonPositiveWithoutWrite() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions()
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("0")
        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.repaymentCalls.isEmpty())
        // Dialog stays open so the user can correct the amount.
        assertEquals(DebtAction.Repayment, viewModel.state.value.activeAction)
    }

    @Test
    fun submitRepaymentVoidUsesRestoredStableIdAndReloadsVoidedFact() = runTest(dispatcher) {
        val firstPageIds = (51 downTo 2).map { "repayment-$it" }
        val repo = FakeDebtDetailActions(
            getResult = Result.success(sampleDebt("d1", rowVersion = 5L, remaining = 50_000L)),
            writeResult = Result.success(sampleDebt("d1", rowVersion = 6L, remaining = 50_000L)),
            historyResult = Result.success(
                repaymentHistoryPage("d1", page = 1, total = 51, publicIds = firstPageIds),
            ),
        ).apply {
            historyPageResults[2] = Result.success(
                repaymentHistoryPage("d1", page = 2, total = 51, publicIds = listOf("repayment-1")),
            )
        }
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()
        viewModel.loadMoreRepaymentHistory()
        advanceUntilIdle()

        repo.historyResult = Result.success(
            repaymentHistory("d1", voidReason = "金额记错了").copy(
                items = listOf(
                    repaymentRecord(
                        publicId = "repayment-51",
                        amountCents = 100L,
                        voidReason = "金额记错了",
                    ),
                ),
            ),
        )
        viewModel.openAction(DebtAction.RepaymentVoid, "repayment-51")
        viewModel.updateReason("金额记错了")
        viewModel.submit()
        advanceUntilIdle()

        val call = repo.repaymentVoidCalls.single()
        assertEquals("d1", call.publicId)
        assertEquals("repayment-51", call.repaymentPublicId)
        assertEquals(5L, call.expectedRowVersion)
        assertEquals("金额记错了", call.reason)
        assertEquals(6L, viewModel.state.value.debt?.rowVersion)
        val reloaded = viewModel.state.value.repaymentHistory?.items?.single()
        assertTrue(reloaded?.isVoided == true)
        assertEquals("金额记错了", reloaded?.voidFact?.reason)
        assertEquals("2026-07-18T00:05:00Z", reloaded?.voidFact?.createdAt)
        assertEquals(1, viewModel.state.value.repaymentHistory?.page)
        assertEquals(1, viewModel.state.value.repaymentHistory?.items?.size)
        assertNull(viewModel.state.value.activeAction)
        assertEquals(
            listOf(
                RepaymentHistoryArgs("d1", 1),
                RepaymentHistoryArgs("d1", 2),
                RepaymentHistoryArgs("d1", 1),
            ),
            repo.historyCalls,
        )
    }

    @Test
    fun staleRepaymentVoidKeepsReasonFactAndEditorOpen() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(
            getResult = Result.success(sampleDebt("d1", rowVersion = 5L)),
            historyResult = Result.success(repaymentHistory("d1")),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        repo.writeResult = Result.failure(RuntimeException("欠款状态已变化，请刷新后再试。"))
        viewModel.openAction(DebtAction.RepaymentVoid, "repayment-1")
        viewModel.updateReason("金额记错了")
        viewModel.submit()
        advanceUntilIdle()

        assertEquals(DebtAction.RepaymentVoid, viewModel.state.value.activeAction)
        assertEquals("金额记错了", viewModel.state.value.reasonInput)
        assertEquals("repayment-1", viewModel.state.value.repaymentToVoidPublicId)
        assertTrue(viewModel.state.value.repaymentHistory?.items?.single()?.isActive == true)
        assertEquals(5L, viewModel.state.value.debt?.rowVersion)
        assertTrue(viewModel.state.value.validationError != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun repaymentVoidRequiresReasonAndViewerCannotOpenActions() = runTest(dispatcher) {
        val viewerViewModel = DebtDetailViewModel(
            FakeDebtDetailActions(
                canModify = false,
                historyResult = Result.success(repaymentHistory("d1")),
            ),
        )
        viewerViewModel.loadDebt("d1")
        advanceUntilIdle()
        viewerViewModel.openAction(DebtAction.RepaymentVoid, "repayment-1")
        assertNull(viewerViewModel.state.value.activeAction)

        val repo = FakeDebtDetailActions(historyResult = Result.success(repaymentHistory("d1")))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.RepaymentVoid, "repayment-1")
        viewModel.submit()
        advanceUntilIdle()

        assertEquals(DebtAction.RepaymentVoid, viewModel.state.value.activeAction)
        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.repaymentVoidCalls.isEmpty())
    }

    @Test
    fun submitAdjustmentAppliesDecreaseSign() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(getResult = Result.success(sampleDebt("d1", rowVersion = 2L)))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateAmount("50")
        viewModel.updateReason("减免")
        viewModel.setAdjustmentSign(increase = false)
        viewModel.submit()
        advanceUntilIdle()

        val call = repo.adjustmentCalls.single()
        // Magnitude 50 with the decrease sign → a negative signed delta.
        assertEquals(-5_000L, call.amountCents)
        assertEquals("减免", call.reason)
        assertEquals(2L, call.expectedRowVersion)
    }

    @Test
    fun submitAdjustmentDefaultsToIncreaseSign() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions()
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateAmount("50")
        viewModel.updateReason("手续费")
        viewModel.submit()
        advanceUntilIdle()

        // No sign toggle → the default (increase) keeps the delta positive.
        assertEquals(5_000L, repo.adjustmentCalls.single().amountCents)
    }

    @Test
    fun submitAdjustmentValidationRequiresReasonWithoutWrite() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions()
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateAmount("50")
        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.adjustmentCalls.isEmpty())
    }

    @Test
    fun submitVoidSendsReasonAndSwapsFold() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(
            getResult = Result.success(sampleDebt("d1", rowVersion = 1L)),
            writeResult = Result.success(sampleDebt("d1", rowVersion = 2L, status = DebtLinkStatuses.VOIDED)),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Void)
        viewModel.updateReason("记错了")
        viewModel.submit()
        advanceUntilIdle()

        val call = repo.voidCalls.single()
        assertEquals("记错了", call.reason)
        assertEquals(1L, call.expectedRowVersion)
        assertEquals(DebtLinkStatuses.VOIDED, viewModel.state.value.debt?.status)
        assertNull(viewModel.state.value.activeAction)
    }

    @Test
    fun submitVoidValidationRequiresReasonWithoutWrite() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions()
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Void)
        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.voidCalls.isEmpty())
    }

    @Test
    fun submitFailureKeepsDialogOpenWithError() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(writeResult = Result.failure(RuntimeException("boom")))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("100")
        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        // Dialog stays open for retry; the user's input is not lost.
        assertEquals(DebtAction.Repayment, viewModel.state.value.activeAction)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun dismissActionClearsDialog() = runTest(dispatcher) {
        val viewModel = DebtDetailViewModel(FakeDebtDetailActions())
        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateAmount("5")
        viewModel.updateReason("x")
        viewModel.dismissAction()

        assertNull(viewModel.state.value.activeAction)
        assertEquals("", viewModel.state.value.amountInput)
        assertEquals("", viewModel.state.value.reasonInput)
    }

    @Test
    fun dismissFlashClearsMessage() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions()
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("100")
        viewModel.submit()
        advanceUntilIdle()
        assertTrue(viewModel.state.value.flashMessage != null)

        viewModel.dismissFlash()

        assertNull(viewModel.state.value.flashMessage)
    }

    // ── ADR-0049 §7.0 / 8e-6e 还款类型纠正 ──────────────────────────────────

    @Test
    fun selectKindSendsOccKindAndSwapsFold() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(getResult = Result.success(sampleDebt("d1", rowVersion = 5L)))
        repo.setKindResult = Result.success(sampleDebt("d1", rowVersion = 6L).copy(debtKind = DebtKinds.REVOLVING))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.selectKind(DebtKinds.REVOLVING)
        advanceUntilIdle()

        val call = repo.setKindCalls.single()
        assertEquals("d1", call.publicId)
        // OCC carrier = the loaded Debt's row_version.
        assertEquals(5L, call.expectedRowVersion)
        assertEquals(DebtKinds.REVOLVING, call.kind)
        // Fold-after Debt swapped in (row_version advanced, new kind) + success flash.
        assertEquals(6L, viewModel.state.value.debt?.rowVersion)
        assertEquals(DebtKinds.REVOLVING, viewModel.state.value.debt?.debtKind)
        assertTrue(viewModel.state.value.flashMessage != null)
        assertNull(viewModel.state.value.error)
    }

    @Test
    fun selectSameKindIsNoOpWithoutWrite() = runTest(dispatcher) {
        // Selecting the already-current kind sends no request (avoids an idle row_version bump).
        val repo = FakeDebtDetailActions(getResult = Result.success(sampleDebt("d1")))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.selectKind(DebtKinds.UNSPECIFIED)
        advanceUntilIdle()

        assertTrue(repo.setKindCalls.isEmpty())
        assertNull(viewModel.state.value.flashMessage)
    }

    @Test
    fun selectKindFailureSurfacesErrorBannerLeavingDebtUnchanged() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(getResult = Result.success(sampleDebt("d1", rowVersion = 5L)))
        repo.setKindResult = Result.failure(RuntimeException("boom"))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.selectKind(DebtKinds.INSTALLMENT)
        advanceUntilIdle()

        // Failure → the screen-level error banner; the loaded Debt (kind + row_version) is unchanged.
        assertTrue(viewModel.state.value.error != null)
        assertEquals(DebtKinds.UNSPECIFIED, viewModel.state.value.debt?.debtKind)
        assertEquals(5L, viewModel.state.value.debt?.rowVersion)
    }

    // ADR-0049 §5.2 (slice 8e-4) 两清庆祝边沿检测。

    @Test
    fun witnessedMemberDebtClearingEmitsCelebration() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(getResult = Result.success(memberDebt(status = DebtLinkStatuses.OPEN)))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("m1")
        advanceUntilIdle()
        // 先见 open：记录非-cleared 先值，但还不撒花。
        assertNull(viewModel.celebration.value)

        repo.getResult = Result.success(memberDebt(status = DebtLinkStatuses.CLEARED))
        viewModel.refresh()
        advanceUntilIdle()

        val celebration = viewModel.celebration.value
        assertTrue(celebration != null)
        assertEquals("小敏", celebration?.counterpartyLabel)
    }

    @Test
    fun firstSightOfAlreadyClearedMemberDebtDoesNotCelebrate() = runTest(dispatcher) {
        // P1#4：债务人首次打开一笔早已 cleared 的成员债（创建者确认时不在场）不该撒花。
        val repo = FakeDebtDetailActions(getResult = Result.success(memberDebt(status = DebtLinkStatuses.CLEARED)))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("m1")
        advanceUntilIdle()

        assertNull(viewModel.celebration.value)
    }

    @Test
    fun forgivenMemberDebtClearingDoesNotCelebrate() = runTest(dispatcher) {
        // §5.6：forgive 落地态也是 cleared，但走暖语分叉不撒「两清」花。
        val repo = FakeDebtDetailActions(getResult = Result.success(memberDebt(status = DebtLinkStatuses.OPEN)))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("m1")
        advanceUntilIdle()

        repo.getResult = Result.success(memberDebt(status = DebtLinkStatuses.CLEARED, isForgiven = true))
        viewModel.refresh()
        advanceUntilIdle()

        assertNull(viewModel.celebration.value)
    }

    @Test
    fun nonPartyMemberDebtClearingDoesNotCelebrate() = runTest(dispatcher) {
        // viewerIsDebtor == null：非当事方（list/fact 路径）目击 cleared 不撒花。
        val repo = FakeDebtDetailActions(
            getResult = Result.success(memberDebt(status = DebtLinkStatuses.OPEN, viewerIsDebtor = null)),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("m1")
        advanceUntilIdle()

        repo.getResult = Result.success(memberDebt(status = DebtLinkStatuses.CLEARED, viewerIsDebtor = null))
        viewModel.refresh()
        advanceUntilIdle()

        assertNull(viewModel.celebration.value)
    }

    @Test
    fun externalDebtClearingDoesNotCelebrate() = runTest(dispatcher) {
        // 外部债走会计框架，open→cleared 不撒「两清」花。
        val repo = FakeDebtDetailActions(getResult = Result.success(sampleDebt("d1", status = DebtLinkStatuses.OPEN)))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        repo.getResult = Result.success(sampleDebt("d1", status = DebtLinkStatuses.CLEARED))
        viewModel.refresh()
        advanceUntilIdle()

        assertNull(viewModel.celebration.value)
    }

    @Test
    fun celebrationDoesNotReplayAfterConsume() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(getResult = Result.success(memberDebt(status = DebtLinkStatuses.OPEN)))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("m1")
        advanceUntilIdle()
        repo.getResult = Result.success(memberDebt(status = DebtLinkStatuses.CLEARED))
        viewModel.refresh()
        advanceUntilIdle()
        assertTrue(viewModel.celebration.value != null)

        viewModel.consumeCelebration()
        // 同一笔 cleared 债再 refresh：crossedEdge 与 per-debt-id 去重都拦下，不重放。
        viewModel.refresh()
        advanceUntilIdle()

        assertNull(viewModel.celebration.value)
    }

    @Test
    fun consumeCelebrationClearsSignal() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(getResult = Result.success(memberDebt(status = DebtLinkStatuses.OPEN)))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("m1")
        advanceUntilIdle()
        repo.getResult = Result.success(memberDebt(status = DebtLinkStatuses.CLEARED))
        viewModel.refresh()
        advanceUntilIdle()
        assertTrue(viewModel.celebration.value != null)

        viewModel.consumeCelebration()

        assertNull(viewModel.celebration.value)
    }

    @Test
    fun consumedCelebrationDoesNotLeakToADifferentDebt() = runTest(dispatcher) {
        // DebtRoute 在详情屏 dispose 时 consume（中途返回会取消浮层的 consume，否则单例 VM 持有的旧信号会
        // 泄漏到下一笔欠款误撒花，对抗审 P2）。consume 后打开另一笔欠款不得复用旧信号。
        val repo = FakeDebtDetailActions(getResult = Result.success(memberDebt(status = DebtLinkStatuses.OPEN)))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("m1")
        advanceUntilIdle()
        repo.getResult = Result.success(memberDebt(status = DebtLinkStatuses.CLEARED))
        viewModel.refresh()
        advanceUntilIdle()
        assertTrue(viewModel.celebration.value != null)
        viewModel.consumeCelebration()

        // 切到另一笔（首次见、已 cleared）：P1#4 不撒花，且旧信号已被 consume 清掉。
        repo.getResult = Result.success(memberDebt(status = DebtLinkStatuses.CLEARED).copy(publicId = "m2"))
        viewModel.loadDebt("m2")
        advanceUntilIdle()

        assertNull(viewModel.celebration.value)
    }

    // ── ADR-0049 §2.1 stale-refresh 代际守卫（功能正确性加固 #2，镜像 DebtGoalViewModel）─────────────

    @Test
    fun staleRefreshDoesNotRevertCommittedWrite() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(
            getResult = Result.success(sampleDebt("d1", rowVersion = 5L, remaining = 50_000L)),
            writeResult = Result.success(sampleDebt("d1", rowVersion = 6L, remaining = 40_000L)),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle() // debt = rv5

        // A slow refresh stalls inside getDebt() (it captured the pre-write rv5 snapshot)...
        val gate = CompletableDeferred<Unit>()
        repo.getGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then the user records a repayment, committing the fold-after rv6.
        repo.getGate = null
        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("100")
        viewModel.submit()
        advanceUntilIdle()
        assertEquals(6L, viewModel.state.value.debt?.rowVersion)

        // Release the now-stale refresh; its rv5 snapshot must NOT revert the committed write — else
        // the next write's OCC carrier would be stale (→ a 409).
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(6L, viewModel.state.value.debt?.rowVersion)
        assertEquals(40_000L, viewModel.state.value.debt?.remainingAmountCents)
    }

    @Test
    fun refreshSupersededByWriteStillClearsLoadingFlag() = runTest(dispatcher) {
        // A refresh dropped because a (non-refresh) write superseded it must still clear isLoading,
        // or the screen sticks "loading".
        val repo = FakeDebtDetailActions(
            getResult = Result.success(sampleDebt("d1", rowVersion = 5L)),
            writeResult = Result.success(sampleDebt("d1", rowVersion = 6L)),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        val gate = CompletableDeferred<Unit>()
        repo.getGate = gate
        viewModel.refresh()
        runCurrent()
        assertTrue(viewModel.state.value.isLoading)

        repo.getGate = null
        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("100")
        viewModel.submit()
        advanceUntilIdle()
        // The stalled refresh still owns the (true) loading flag; the write didn't touch it.
        assertTrue(viewModel.state.value.isLoading)

        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(false, viewModel.state.value.isLoading)
    }

    @Test
    fun slowLoadDoesNotClobberAReopenedDebt() = runTest(dispatcher) {
        // The reusable detail VM is reopened with another Debt while a prior load is still in flight;
        // the stale load must not overwrite the reopened Debt.
        val repo = FakeDebtDetailActions(getResult = Result.success(sampleDebt("A")))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("A")
        advanceUntilIdle()

        // A slow re-fetch of A stalls (it captured A's snapshot)...
        val gate = CompletableDeferred<Unit>()
        repo.getGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then the user reopens the detail on a different Debt B.
        repo.getGate = null
        repo.getResult = Result.success(sampleDebt("B"))
        viewModel.loadDebt("B")
        advanceUntilIdle()
        assertEquals("B", viewModel.state.value.debt?.publicId)

        // Release the stale A load; it must NOT clobber the reopened Debt B.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals("B", viewModel.state.value.debt?.publicId)
    }

    @Test
    fun staleDroppedMemberSnapshotDoesNotCelebrate() = runTest(dispatcher) {
        // The gen-drop must run BEFORE detectSettleCelebration: a discarded stale snapshot must not
        // fire a 两清 celebration (nor record a status edge). Pinned with a member debt — the only
        // case where the guard interacts with celebration detection.
        val repo = FakeDebtDetailActions(
            getResult = Result.success(memberDebt(status = DebtLinkStatuses.OPEN)),
            // A repayment that leaves it OPEN → no real edge, so the committed write never celebrates.
            writeResult = Result.success(memberDebt(status = DebtLinkStatuses.OPEN)),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("m1")
        advanceUntilIdle() // open recorded as the non-cleared prior; no celebration

        // A slow refresh stalls having captured a CLEARED member snapshot...
        val gate = CompletableDeferred<Unit>()
        repo.getGate = gate
        repo.getResult = Result.success(memberDebt(status = DebtLinkStatuses.CLEARED))
        viewModel.refresh()
        runCurrent()

        // ...superseded by a committed repayment (still OPEN, no edge).
        repo.getGate = null
        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("100")
        viewModel.submit()
        advanceUntilIdle()

        // Release the stale CLEARED snapshot; it is dropped before celebration detection, so no 两清
        // fires from a discarded snapshot and the committed OPEN state is retained (also catches full
        // guard removal — the CLEARED snapshot would otherwise both celebrate and overwrite).
        gate.complete(Unit)
        advanceUntilIdle()
        assertNull(viewModel.celebration.value)
        assertEquals(DebtLinkStatuses.OPEN, viewModel.state.value.debt?.status)
    }
}

internal data class WriteArgs(
    val publicId: String,
    val expectedRowVersion: Long,
    val amountCents: Long?,
    val reason: String?,
)

internal data class RepaymentVoidArgs(
    val publicId: String,
    val repaymentPublicId: String,
    val expectedRowVersion: Long,
    val reason: String,
)

internal data class RepaymentHistoryArgs(val publicId: String, val page: Int)

internal data class KindArgs(val publicId: String, val expectedRowVersion: Long, val kind: String)

internal class FakeDebtDetailActions(
    private val canModify: Boolean = true,
    var getResult: Result<Debt> = Result.success(sampleDebt()),
    var writeResult: Result<Debt> = Result.success(sampleDebt()),
    var historyResult: Result<DebtRepaymentHistory> = Result.success(emptyRepaymentHistory()),
) : DebtDetailActions {
    val repaymentCalls = mutableListOf<WriteArgs>()
    val repaymentVoidCalls = mutableListOf<RepaymentVoidArgs>()
    val adjustmentCalls = mutableListOf<WriteArgs>()
    val voidCalls = mutableListOf<WriteArgs>()
    val setKindCalls = mutableListOf<KindArgs>()
    val historyCalls = mutableListOf<RepaymentHistoryArgs>()
    val historyPageResults = mutableMapOf<Int, Result<DebtRepaymentHistory>>()
    var setKindResult: Result<Debt> = Result.success(sampleDebt())

    /** When set, getDebt() stalls until completed — used to interleave a slow load. */
    var getGate: CompletableDeferred<Unit>? = null

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun listDebts(): Result<List<Debt>> = Result.success(emptyList())

    override suspend fun getDebt(publicId: String): Result<Debt> {
        // Capture the result at entry so a stalled load returns the snapshot it started with, even
        // if a newer load swaps getResult in the meantime.
        val captured = getResult
        getGate?.await()
        return captured
    }

    override suspend fun listRepaymentFacts(
        publicId: String,
        page: Int,
    ): Result<DebtRepaymentHistory> {
        historyCalls += RepaymentHistoryArgs(publicId, page)
        return historyPageResults[page] ?: historyResult
    }

    override suspend fun createDebt(draft: DebtDraft): Result<Debt> = Result.success(sampleDebt())

    override suspend fun parseDebtBillImage(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
    ): Result<DebtBillSuggestion> = Result.failure(UnsupportedOperationException())

    override suspend fun recordRepayment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
    ): Result<DebtRepaymentFact> {
        repaymentCalls += WriteArgs(publicId, expectedRowVersion, amountCents, null)
        return writeResult.map { DebtRepaymentFact("repayment-1", amountCents, it) }
    }

    override suspend fun voidRepayment(
        publicId: String,
        repaymentPublicId: String,
        expectedRowVersion: Long,
        reason: String,
    ): Result<Debt> {
        repaymentVoidCalls += RepaymentVoidArgs(publicId, repaymentPublicId, expectedRowVersion, reason)
        return writeResult
    }

    override suspend fun recordAdjustment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
        reason: String,
    ): Result<Debt> {
        adjustmentCalls += WriteArgs(publicId, expectedRowVersion, amountCents, reason)
        return writeResult
    }

    override suspend fun voidDebt(
        publicId: String,
        expectedRowVersion: Long,
        reason: String,
    ): Result<Debt> {
        voidCalls += WriteArgs(publicId, expectedRowVersion, null, reason)
        return writeResult
    }

    override suspend fun setDebtKind(
        publicId: String,
        expectedRowVersion: Long,
        debtKind: String,
    ): Result<Debt> {
        setKindCalls += KindArgs(publicId, expectedRowVersion, debtKind)
        return setKindResult
    }
}

private fun repaymentHistory(
    debtPublicId: String,
    amountCents: Long = 10_000L,
    voidReason: String? = null,
): DebtRepaymentHistory {
    return DebtRepaymentHistory(
        debtPublicId = debtPublicId,
        homeCurrencyCode = "CNY",
        items = listOf(
            repaymentRecord(
                publicId = "repayment-1",
                amountCents = amountCents,
                voidReason = voidReason,
            ),
        ),
        page = 1,
        pageSize = 50,
        total = 1,
    )
}

internal fun repaymentHistoryPage(
    debtPublicId: String,
    page: Int,
    total: Int,
    publicIds: List<String>,
): DebtRepaymentHistory = DebtRepaymentHistory(
    debtPublicId = debtPublicId,
    homeCurrencyCode = "CNY",
    items = publicIds.mapIndexed { index, publicId ->
        repaymentRecord(publicId = publicId, amountCents = (index + 1L) * 100L)
    },
    page = page,
    pageSize = 50,
    total = total,
)

private fun repaymentRecord(
    publicId: String,
    amountCents: Long,
    voidReason: String? = null,
): DebtRepaymentRecord {
    val voidFact = voidReason?.let {
        DebtRepaymentVoidFact(
            publicId = "void-$publicId",
            reason = it,
            createdAt = "2026-07-18T00:05:00Z",
        )
    }
    return DebtRepaymentRecord(
        publicId = publicId,
        amountCents = amountCents,
        originalCurrencyCode = null,
        originalAmountMinor = null,
        exchangeRateToCny = null,
        exchangeRateDate = null,
        exchangeRateSource = null,
        paidAt = "2026-07-18T00:00:00Z",
        createdAt = "2026-07-18T00:00:01Z",
        status = if (voidFact == null) {
            DebtRepaymentFactStatuses.ACTIVE
        } else {
            DebtRepaymentFactStatuses.VOIDED
        },
        voidFact = voidFact,
    )
}

private fun emptyRepaymentHistory(): DebtRepaymentHistory = DebtRepaymentHistory(
    debtPublicId = "d1",
    homeCurrencyCode = "CNY",
    items = emptyList(),
    page = 1,
    pageSize = 50,
    total = 0,
)

private fun sampleDebt(
    publicId: String = "d1",
    rowVersion: Long = 1L,
    remaining: Long = 50_000L,
    status: String = DebtLinkStatuses.OPEN,
): Debt = Debt(
    publicId = publicId,
    ledgerId = "owner",
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyAccountId = null,
    counterpartyLabel = "房东",
    principalAmountCents = 50_000,
    remainingAmountCents = remaining,
    paidAmountCents = 50_000 - remaining,
    status = status,
    sourceType = DebtSourceTypes.MANUAL,
    sourceId = null,
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-15T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = rowVersion,
)

// A member Debt sample for §5.2 celebration tests; defaults to the creditor viewer (viewerIsDebtor=false).
// Uses copy() so the base sampleDebt stays at four params (avoids the LongParameterList gate).
private fun memberDebt(
    status: String,
    viewerIsDebtor: Boolean? = false,
    isForgiven: Boolean = false,
): Debt = sampleDebt(publicId = "m1", status = status).copy(
    counterpartyType = DebtCounterpartyTypes.MEMBER,
    counterpartyLabel = "小敏",
    viewerIsDebtor = viewerIsDebtor,
    isForgiven = isForgiven,
)

private fun DebtDetailViewModel.updateAmount(value: String) = updateActionInput(amount = value)

private fun DebtDetailViewModel.updateReason(value: String) = updateActionInput(reason = value)

private fun DebtDetailViewModel.setAdjustmentSign(increase: Boolean) =
    updateActionInput(adjustmentIncrease = increase)
