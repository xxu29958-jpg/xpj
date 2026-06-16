package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.DebtProposalActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.MemberProposalStatuses
import com.ticketbox.domain.model.MemberRepaymentProposal
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
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
        val repo = FakeProposalActions(
            canModify = false,
            listResult = Result.success(listOf(sampleProposal())),
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
        val repo = FakeProposalActions(listResult = Result.success(listOf(sampleProposal())))
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
        val repo = FakeProposalActions(listResult = Result.failure(RuntimeException("offline")))
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        assertTrue(viewModel.state.value.proposals.isEmpty())
        assertTrue(viewModel.state.value.error != null)
    }

    @Test
    fun openConfirmPrefillsProposedAmount() = runTest(dispatcher) {
        val viewModel = MemberRepaymentProposalViewModel(FakeProposalActions())
        viewModel.openForm(ProposalForm.Confirm, sampleProposal(proposedAmountCents = 20_050))

        assertEquals(ProposalForm.Confirm, viewModel.state.value.activeForm)
        assertEquals("200.50", viewModel.state.value.amountInput)
    }

    @Test
    fun submitProposeSendsAmountAndNote() = runTest(dispatcher) {
        val repo = FakeProposalActions()
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Propose)
        viewModel.updateAmount("150")
        viewModel.updateNote("微信转账")
        viewModel.submit(expectedRowVersion = 7L)
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
    fun submitProposeValidatesNonPositiveWithoutCall() = runTest(dispatcher) {
        val repo = FakeProposalActions()
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Propose)
        viewModel.updateAmount("0")
        viewModel.submit(expectedRowVersion = 1L)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.proposeCalls.isEmpty())
        // Form stays open so the user can correct the amount.
        assertEquals(ProposalForm.Propose, viewModel.state.value.activeForm)
    }

    @Test
    fun submitConfirmFullSendsNullAmountAndBumpsFold() = runTest(dispatcher) {
        val repo = FakeProposalActions(
            listResult = Result.success(listOf(sampleProposal(publicId = "p1", proposedAmountCents = 20_000))),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.submit(expectedRowVersion = 5L)
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
        val repo = FakeProposalActions(
            listResult = Result.success(listOf(sampleProposal(publicId = "p1", proposedAmountCents = 20_000))),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.updateAmount("150")
        viewModel.submit(expectedRowVersion = 5L)
        advanceUntilIdle()

        // A lower amount than proposed → a partial confirm carries the explicit cents.
        assertEquals(15_000L, repo.confirmCalls.single().confirmedAmountCents)
    }

    @Test
    fun submitConfirmValidatesOverProposedWithoutCall() = runTest(dispatcher) {
        val repo = FakeProposalActions(
            listResult = Result.success(listOf(sampleProposal(publicId = "p1", proposedAmountCents = 20_000))),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.updateAmount("300")
        viewModel.submit(expectedRowVersion = 5L)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.confirmCalls.isEmpty())
    }

    @Test
    fun withdrawCallsRepoRefreshesAndFlashes() = runTest(dispatcher) {
        val repo = FakeProposalActions(
            listResult = Result.success(listOf(sampleProposal(publicId = "p1"))),
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
        val repo = FakeProposalActions(
            listResult = Result.success(listOf(sampleProposal(publicId = "p1"))),
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
        val repo = FakeProposalActions(
            listResult = Result.success(listOf(sampleProposal(publicId = "p1"))),
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
        val repo = FakeProposalActions(
            listResult = Result.success(listOf(sampleProposal(publicId = "p1", proposedAmountCents = 20_000))),
            confirmResult = Result.failure(RuntimeException("boom")),
        )
        val viewModel = MemberRepaymentProposalViewModel(repo)
        viewModel.load("d1")
        advanceUntilIdle()

        viewModel.openForm(ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.submit(expectedRowVersion = 5L)
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
                sampleProposal(publicId = "newPending", status = MemberProposalStatuses.PENDING),
                sampleProposal(publicId = "rejected", status = MemberProposalStatuses.REJECTED),
                sampleProposal(publicId = "older", status = MemberProposalStatuses.WITHDRAWN),
            ),
        )
        assertEquals("rejected", state.latestResolvedProposal?.publicId)
    }

    @Test
    fun showDebtorAfterRejectOnlyWhenLatestResolvedRejectedAndNoPending() {
        // §1.4: latest resolved is a rejection and nothing is in flight → show the neutral re-propose hint.
        val rejectedNoPending = MemberProposalUiState(
            proposals = listOf(sampleProposal(publicId = "p1", status = MemberProposalStatuses.REJECTED)),
        )
        assertTrue(rejectedNoPending.showDebtorAfterReject)

        // A live re-proposal (pending) suppresses the hint even though an older one was rejected.
        val rejectedThenPending = MemberProposalUiState(
            proposals = listOf(
                sampleProposal(publicId = "p2", status = MemberProposalStatuses.PENDING),
                sampleProposal(publicId = "p1", status = MemberProposalStatuses.REJECTED),
            ),
        )
        assertEquals(false, rejectedThenPending.showDebtorAfterReject)

        // A non-rejected latest resolution (e.g. withdrawn) does not show the hint, nor does an empty list.
        val withdrawn = MemberProposalUiState(
            proposals = listOf(sampleProposal(publicId = "p3", status = MemberProposalStatuses.WITHDRAWN)),
        )
        assertEquals(false, withdrawn.showDebtorAfterReject)
        assertEquals(false, MemberProposalUiState().showDebtorAfterReject)
    }

    // ── 8e ④ forgive (creditor waiver) ───────────────────────────────────────

    @Test
    fun forgiveCallsRepoBumpsFoldFlashesAndRefreshes() = runTest(dispatcher) {
        val repo = FakeProposalActions(listResult = Result.success(listOf(sampleProposal(publicId = "p1"))))
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
        val repo = FakeProposalActions(
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
        val repo = FakeProposalActions(forgiveResult = Result.failure(RuntimeException()))
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
}

private data class ProposeArgs(
    val debtPublicId: String,
    val proposedAmountCents: Long,
    val note: String?,
    val supersedesProposalPublicId: String?,
)

private data class ConfirmArgs(
    val debtPublicId: String,
    val proposalPublicId: String,
    val expectedRowVersion: Long,
    val confirmedAmountCents: Long?,
)

private class FakeProposalActions(
    private val canModify: Boolean = true,
    var listResult: Result<List<MemberRepaymentProposal>> = Result.success(emptyList()),
    var proposalResult: Result<MemberRepaymentProposal> = Result.success(sampleProposal()),
    var confirmResult: Result<Debt> = Result.success(sampleDebt()),
    var forgiveResult: Result<Debt> = Result.success(sampleDebt(status = DebtLinkStatuses.CLEARED, isForgiven = true)),
) : DebtProposalActions {
    val proposeCalls = mutableListOf<ProposeArgs>()
    val withdrawCalls = mutableListOf<Pair<String, String>>()
    val confirmCalls = mutableListOf<ConfirmArgs>()
    val rejectCalls = mutableListOf<Pair<String, String>>()
    val forgiveCalls = mutableListOf<Pair<String, Long>>()
    var listCalls = 0

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun listRepaymentProposals(debtPublicId: String): Result<List<MemberRepaymentProposal>> {
        listCalls++
        return listResult
    }

    override suspend fun proposeRepayment(
        debtPublicId: String,
        proposedAmountCents: Long,
        note: String?,
        supersedesProposalPublicId: String?,
    ): Result<MemberRepaymentProposal> {
        proposeCalls += ProposeArgs(debtPublicId, proposedAmountCents, note, supersedesProposalPublicId)
        return proposalResult
    }

    override suspend fun withdrawRepaymentProposal(
        debtPublicId: String,
        proposalPublicId: String,
    ): Result<MemberRepaymentProposal> {
        withdrawCalls += debtPublicId to proposalPublicId
        return proposalResult
    }

    override suspend fun confirmRepaymentProposal(
        debtPublicId: String,
        proposalPublicId: String,
        expectedRowVersion: Long,
        confirmedAmountCents: Long?,
    ): Result<Debt> {
        confirmCalls += ConfirmArgs(debtPublicId, proposalPublicId, expectedRowVersion, confirmedAmountCents)
        return confirmResult
    }

    override suspend fun rejectRepaymentProposal(
        debtPublicId: String,
        proposalPublicId: String,
    ): Result<MemberRepaymentProposal> {
        rejectCalls += debtPublicId to proposalPublicId
        return proposalResult
    }

    override suspend fun forgiveDebt(debtPublicId: String, expectedRowVersion: Long): Result<Debt> {
        forgiveCalls += debtPublicId to expectedRowVersion
        return forgiveResult
    }
}

private fun sampleProposal(
    publicId: String = "p1",
    proposedAmountCents: Long = 20_000L,
    status: String = MemberProposalStatuses.PENDING,
): MemberRepaymentProposal = MemberRepaymentProposal(
    publicId = publicId,
    debtPublicId = "d1",
    status = status,
    proposedAmountCents = proposedAmountCents,
    confirmedAmountCents = null,
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    paidAt = "2026-06-16T00:00:00Z",
    note = null,
    expiresAt = "2026-07-16T00:00:00Z",
    createdAt = "2026-06-16T00:00:00Z",
    resolvedAt = null,
    supersedesProposalPublicId = null,
    committedRepaymentPublicId = null,
)

private fun sampleDebt(
    status: String = DebtLinkStatuses.CLEARED,
    isForgiven: Boolean = false,
): Debt = Debt(
    publicId = "d1",
    ledgerId = "owner",
    direction = DebtDirections.OWED_TO_ME,
    counterpartyType = DebtCounterpartyTypes.MEMBER,
    counterpartyAccountId = 42,
    counterpartyLabel = "家人",
    principalAmountCents = 20_000,
    remainingAmountCents = 0,
    paidAmountCents = 20_000,
    status = status,
    sourceType = DebtSourceTypes.BILL_SPLIT,
    sourceId = "inv-1",
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-16T00:00:00Z",
    updatedAt = "2026-06-16T00:00:00Z",
    rowVersion = 6,
    isForgiven = isForgiven,
)
