package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MemberProposalStatuses
import com.ticketbox.domain.model.UiText
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

class MemberRepaymentProposalViewModelTest {

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
    fun loadFetchesProposalsAndReflectsRole() = runTest(dispatcher) {
        val repo = ProposalTestActions(
            canModify = false,
            listResult = Result.success(listOf(sampleMemberProposal())),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        assertEquals(1, viewModel.state.value.proposals.size)
        assertEquals(false, viewModel.state.value.canModify)
        assertEquals(false, viewModel.state.value.isLoading)
        assertEquals(1, repo.listCalls)
    }

    @Test
    fun loadClearsStaleProposalsBeforeRefetch() = runTest(dispatcher) {
        val repo = ProposalTestActions(listResult = Result.success(listOf(sampleMemberProposal())))
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()
        assertEquals(1, viewModel.state.value.proposals.size)

        // Switching to another Debt clears the previous收发箱 synchronously, before the refetch lands.
        viewModel.load("d2")
        assertTrue(viewModel.state.value.proposals.isEmpty())
    }

    @Test
    fun refreshFailureSurfacesError() = runTest(dispatcher) {
        val repo = ProposalTestActions(listResult = Result.failure(RuntimeException("offline")))
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        assertTrue(viewModel.state.value.proposals.isEmpty())
        assertTrue(viewModel.state.value.error != null)
    }

    @Test
    fun openConfirmPrefillsProposedAmount() = runTest(dispatcher) {
        val viewModel = MemberRepaymentProposalViewModel(ProposalTestActions())
        viewModel.openForm(ProposalForm.Confirm, sampleMemberProposal(proposedAmountCents = 20_050))

        assertEquals(ProposalForm.Confirm, viewModel.state.value.activeForm)
        assertEquals("200.50", viewModel.state.value.amountInput)
    }

    @Test
    fun submitProposeSendsAmountAndNote() = runTest(dispatcher) {
        val repo = ProposalTestActions()
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Propose)
        viewModel.updateAmount("150")
        viewModel.updateNote("微信转账")
        viewModel.submit(expectedRowVersion = 7L, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        val call = repo.proposeCalls.single()
        assertEquals("d1", call.debtPublicId)
        assertEquals(15_000L, call.proposedAmountCents)
        assertEquals("微信转账", call.note)
        assertNull(call.supersedesProposalPublicId)
        // Propose does NOT change the fold.
        assertEquals(0, viewModel.state.value.foldChangedAt)
        assertNull(viewModel.state.value.activeForm)
        assertTrue(viewModel.state.value.flashMessage != null)
    }

    @Test
    fun submitProposeAcceptsExactTrailingZeroAmount() = runTest(dispatcher) {
        // C07：1.230 精确等于 123 minor；不得在客户端做 HALF_UP。
        val repo = ProposalTestActions()
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Propose)
        viewModel.updateAmount("1.230")
        viewModel.submit(expectedRowVersion = 7L, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        assertEquals(123L, repo.proposeCalls.single().proposedAmountCents)
    }

    @Test
    fun submitProposeValidatesNonPositiveWithoutCall() = runTest(dispatcher) {
        val repo = ProposalTestActions()
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Propose)
        viewModel.updateAmount("0")
        viewModel.submit(expectedRowVersion = 1L, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.proposeCalls.isEmpty())
        // Form stays open so the user can correct the amount.
        assertEquals(ProposalForm.Propose, viewModel.state.value.activeForm)
    }

    @Test
    fun submitConfirmFullSendsNullAmountAndBumpsFold() = runTest(dispatcher) {
        val repo = ProposalTestActions(
            listResult = Result.success(listOf(sampleMemberProposal(publicId = "p1", proposedAmountCents = 20_000))),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.submit(expectedRowVersion = 5L, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        val call = repo.confirmCalls.single()
        assertEquals("p1", call.proposalPublicId)
        assertEquals(5L, call.expectedRowVersion)
        // Amount equals the proposed amount → full confirm → confirmedAmountCents null.
        assertNull(call.confirmedAmountCents)
        // Confirm changed the fold → the host detail screen is told to refresh.
        assertEquals(1, viewModel.state.value.foldChangedAt)
    }

    @Test
    fun submitConfirmPartialSendsConfirmedAmount() = runTest(dispatcher) {
        val repo = ProposalTestActions(
            listResult = Result.success(listOf(sampleMemberProposal(publicId = "p1", proposedAmountCents = 20_000))),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.updateAmount("150")
        viewModel.submit(expectedRowVersion = 5L, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        // A lower amount than proposed → a partial confirm carries the explicit cents.
        assertEquals(15_000L, repo.confirmCalls.single().confirmedAmountCents)
    }

    @Test
    fun submitConfirmValidatesOverProposedWithoutCall() = runTest(dispatcher) {
        val repo = ProposalTestActions(
            listResult = Result.success(listOf(sampleMemberProposal(publicId = "p1", proposedAmountCents = 20_000))),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.updateAmount("300")
        viewModel.submit(expectedRowVersion = 5L, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.confirmCalls.isEmpty())
    }

    @Test
    fun withdrawCallsRepoRefreshesAndFlashes() = runTest(dispatcher) {
        val repo = ProposalTestActions(
            listResult = Result.success(listOf(sampleMemberProposal(publicId = "p1"))),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.withdraw("p1")
        advanceUntilIdle()

        assertEquals("d1" to "p1", repo.withdrawCalls.single())
        // No fold change on withdraw; a fresh list re-fetch + success flash.
        assertEquals(0, viewModel.state.value.foldChangedAt)
        assertEquals(2, repo.listCalls) // initial load + refresh after withdraw
        assertTrue(viewModel.state.value.flashMessage != null)
    }

    @Test
    fun rejectCallsRepoRefreshesAndFlashes() = runTest(dispatcher) {
        val repo = ProposalTestActions(
            listResult = Result.success(listOf(sampleMemberProposal(publicId = "p1"))),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.reject("p1")
        advanceUntilIdle()

        assertEquals("d1" to "p1", repo.rejectCalls.single())
        assertEquals(0, viewModel.state.value.foldChangedAt)
        assertTrue(viewModel.state.value.flashMessage != null)
    }

    @Test
    fun actionFailureSurfacesError() = runTest(dispatcher) {
        val repo = ProposalTestActions(
            listResult = Result.success(listOf(sampleMemberProposal(publicId = "p1"))),
            proposalResult = Result.failure(RuntimeException("boom")),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.reject("p1")
        advanceUntilIdle()

        assertTrue(viewModel.state.value.error != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun submitFailureKeepsFormOpenWithValidationError() = runTest(dispatcher) {
        // submit()'s onFailure diverges from reject()/withdraw(): it surfaces an in-form
        // validationError (not the action-bar error) and keeps the form open for retry.
        val repo = ProposalTestActions(
            listResult = Result.success(listOf(sampleMemberProposal(publicId = "p1", proposedAmountCents = 20_000))),
            confirmResult = Result.failure(RuntimeException("boom")),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.submit(expectedRowVersion = 5L, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
        assertEquals(ProposalForm.Confirm, viewModel.state.value.activeForm)
    }

    @Test
    fun latestResolvedProposalPicksNewestNonPending() {
        // Backend returns proposals newest-first (created_at desc); the first non-pending is the latest resolved.
        val state = MemberProposalUiState(
            proposals = listOf(
                sampleMemberProposal(publicId = "newPending", status = MemberProposalStatuses.PENDING),
                sampleMemberProposal(publicId = "rejected", status = MemberProposalStatuses.REJECTED),
                sampleMemberProposal(publicId = "older", status = MemberProposalStatuses.WITHDRAWN),
            ),
        )
        assertEquals("rejected", state.latestResolvedProposal?.publicId)
    }

    @Test
    fun showDebtorAfterRejectOnlyWhenLatestResolvedRejectedAndNoPending() {
        // §1.4: latest resolved is a rejection and nothing is in flight → show the neutral re-propose hint.
        val rejectedNoPending = MemberProposalUiState(
            proposals = listOf(sampleMemberProposal(publicId = "p1", status = MemberProposalStatuses.REJECTED)),
        )
        assertTrue(rejectedNoPending.showDebtorAfterReject)

        // A live re-proposal (pending) suppresses the hint even though an older one was rejected.
        val rejectedThenPending = MemberProposalUiState(
            proposals = listOf(
                sampleMemberProposal(publicId = "p2", status = MemberProposalStatuses.PENDING),
                sampleMemberProposal(publicId = "p1", status = MemberProposalStatuses.REJECTED),
            ),
        )
        assertEquals(false, rejectedThenPending.showDebtorAfterReject)

        // A non-rejected latest resolution (e.g. withdrawn) does not show the hint, nor does an empty list.
        val withdrawn = MemberProposalUiState(
            proposals = listOf(sampleMemberProposal(publicId = "p3", status = MemberProposalStatuses.WITHDRAWN)),
        )
        assertEquals(false, withdrawn.showDebtorAfterReject)
        assertEquals(false, MemberProposalUiState().showDebtorAfterReject)
    }

    // ── 8e ④ forgive (creditor waiver) ───────────────────────────────────────

    @Test
    fun forgiveCallsRepoBumpsFoldFlashesAndRefreshes() = runTest(dispatcher) {
        val repo = ProposalTestActions(listResult = Result.success(listOf(sampleMemberProposal(publicId = "p1"))))
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.forgive(expectedRowVersion = 7L)
        advanceUntilIdle()

        assertEquals("d1" to 7L, repo.forgiveCalls.single())
        // Forgive clears the Debt → fold changed → the host detail screen is told to refresh.
        assertEquals(1, viewModel.state.value.foldChangedAt)
        assertEquals(2, repo.listCalls) // initial load + refresh after forgive
        assertTrue(viewModel.state.value.flashMessage != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun forgiveConflictSurfacesNeutralConflictCopy() = runTest(dispatcher) {
        // §4.3 / P2#10: an OCC / already-settled 409 (backend `state_conflict`) shows the warm
        // "有人刚记了一笔" copy (errorCode branch), not the generic failed fallback; fold untouched.
        val repo = ProposalTestActions(
            forgiveResult = Result.failure(RepositoryException("欠款或提案状态已变化，请刷新后再试。", errorCode = "state_conflict")),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.forgive(expectedRowVersion = 1L)
        advanceUntilIdle()

        val error = viewModel.state.value.error
        assertTrue(error is UiText.Res)
        assertEquals(R.string.debt_member_forgive_conflict, (error as UiText.Res).id)
        assertEquals(0, viewModel.state.value.foldChangedAt)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun forgiveGenericFailureUsesFailedFallback() = runTest(dispatcher) {
        // A non-coded failure (e.g. a transport error with no message) falls back to the
        // forgive-specific failed copy, not the conflict copy.
        val repo = ProposalTestActions(forgiveResult = Result.failure(RuntimeException()))
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.forgive(expectedRowVersion = 1L)
        advanceUntilIdle()

        val error = viewModel.state.value.error
        assertTrue(error is UiText.Res)
        assertEquals(R.string.debt_member_forgive_failed, (error as UiText.Res).id)
        assertEquals(0, viewModel.state.value.foldChangedAt)
    }

    // ── ADR-0049 §2.1 stale-refresh 代际守卫（功能正确性加固 #2，镜像 DebtGoalViewModel）─────────────

    @Test
    fun staleRefreshDoesNotRevertAfterAction() = runTest(dispatcher) {
        // A slow earlier refresh must not bring back a withdrawn proposal after the action's own
        // refresh delivered the post-action (empty) list.
        val repo = ProposalTestActions(listResult = Result.success(listOf(sampleMemberProposal(publicId = "p1"))))
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle() // proposals = [p1]

        // A slow refresh stalls inside listRepaymentProposals() (it captured [p1])...
        val gate = CompletableDeferred<Unit>()
        repo.listGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then the debtor withdraws; the action's success refresh delivers the empty 收发箱.
        repo.listGate = null
        repo.listResult = Result.success(emptyList())
        viewModel.withdraw("p1")
        advanceUntilIdle()
        assertTrue(viewModel.state.value.proposals.isEmpty())

        // Release the stale refresh; the withdrawn proposal must NOT reappear.
        gate.complete(Unit)
        advanceUntilIdle()
        assertTrue(viewModel.state.value.proposals.isEmpty())
    }

    @Test
    fun staleRefreshDoesNotClobberSwitchedDebt() = runTest(dispatcher) {
        // Switching member debts: a slow prior refresh of d1 must not show d1's 收发箱 under d2.
        val repo = ProposalTestActions(listResult = Result.success(listOf(sampleMemberProposal(publicId = "pA"))))
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        // A slow refresh of d1 stalls (it captured d1's proposals)...
        val gate = CompletableDeferred<Unit>()
        repo.listGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then the user switches to d2.
        repo.listGate = null
        repo.listResult = Result.success(listOf(sampleMemberProposal(publicId = "pB")))
        viewModel.load("d2")
        advanceUntilIdle()
        assertEquals("pB", viewModel.state.value.proposals.single().publicId)

        // Release the stale d1 refresh; d1's proposals must NOT leak under d2.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals("pB", viewModel.state.value.proposals.single().publicId)
    }

    @Test
    fun confirmParsesInProposalFrozenCurrencyWhenMatched() = runTest(dispatcher) {
        // PR#255 R7-3：确认金额按 proposal 冻结币种解析（服务端 confirmed 与 proposed 同单位
        // 比较）。JPY proposal 1200 minor 预填 "1200"（零小数整数），与宿主欠款同币种时
        // 全额确认成功（confirmedAmountCents=null），不被 CNY 口径拒/缩放。
        val repo = ProposalTestActions(
            listResult = Result.success(
                listOf(sampleMemberProposal(publicId = "p1", proposedAmountCents = 1_200).copy(homeCurrencyCode = "JPY")),
            ),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        assertEquals("1200", viewModel.state.value.amountInput)
        viewModel.submit(expectedRowVersion = 5L, currency = CurrencyCode.JPY)
        advanceUntilIdle()

        val call = repo.confirmCalls.single()
        assertNull(call.confirmedAmountCents) // 等于提出金额 → 全额确认
        assertEquals(1, viewModel.state.value.foldChangedAt)
    }

    @Test
    fun confirmBlockedWhenProposalCurrencyDriftsFromDebt() = runTest(dispatcher) {
        // R7-3：installation 漂移实例 —— CNY proposal（50000 minor 预填 "500.00"）挂在 JPY
        // 宿主欠款上：JPY 解析会拒/缩 100×，服务端又会把 repayment 按 proposal 口径折进
        // 异币种欠款 → fail closed 禁确认（亮 mismatch 错误，不可达写路径）。
        val repo = ProposalTestActions(
            listResult = Result.success(
                listOf(sampleMemberProposal(publicId = "p1", proposedAmountCents = 50_000)),
            ),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        assertEquals("500.00", viewModel.state.value.amountInput)
        viewModel.submit(expectedRowVersion = 5L, currency = CurrencyCode.JPY)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.confirmCalls.isEmpty())
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun prefillSkippedAndSubmitBlockedWhenProposalCurrencyUnsupported() = runTest(dispatcher) {
        // R7-2/R7-3：proposal 码在支持集外 → 不预填（禁落 CNY 兜底渲染），submit 同样
        // fail closed。
        val repo = ProposalTestActions(
            listResult = Result.success(
                listOf(sampleMemberProposal(publicId = "p1", proposedAmountCents = 1_200).copy(homeCurrencyCode = "XXX")),
            ),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        assertEquals("", viewModel.state.value.amountInput)
        viewModel.submit(expectedRowVersion = 5L, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.confirmCalls.isEmpty())
    }
}
