package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import com.ticketbox.data.remote.dto.BillSplitChangeCreateRequestDto
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.SplitAgreementActions
import com.ticketbox.data.repository.SplitAgreementPayload
import com.ticketbox.data.repository.SPLIT_ACCEPT
import com.ticketbox.data.repository.SPLIT_CREATE
import com.ticketbox.data.repository.splitTestAgreement
import com.ticketbox.data.repository.splitTestProposal
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class SplitAgreementViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun teardown() { Dispatchers.resetMain() }

    @Test fun draftsSurviveOriginalReturnRoundTripButNeverCrossBinding() = runTest(dispatcher) {
        val repo = SplitProbe()
        val model = SplitAgreementViewModel(repo)
        val task = memberDebtTask("original")
        model.load(task); advanceUntilIdle()
        model.editDraft(share = "12.00"); model.refresh(); advanceUntilIdle()
        model.editDraft(settlement = "-3.00"); model.editDraft(reason = "先处理返还申报")
        model.load(task.copy(debtPublicId = "return")); advanceUntilIdle()
        model.load(task); advanceUntilIdle()
        assertEquals("12.00", model.state.value.shareInput)
        assertEquals("-3.00", model.state.value.settlementInput)
        assertEquals("先处理返还申报", model.state.value.reason)
        model.load(task.copy(binding = task.binding.copy(bindingRevision = "new"))); advanceUntilIdle()
        assertEquals("", model.state.value.reason)
        assertEquals("-10.00", model.state.value.settlementInput)
    }

    @Test fun specialSettlementUsesServerDefaultAndRequiresExplicitConfirmation() = runTest(dispatcher) {
        val repo = SplitProbe().apply { value = splitTestAgreement().copy(
            preview = splitTestAgreement().preview.copy(defaultSettlementNetAmountCents = 0, cashBasedSettlementNetAmountCents = 1000)) }
        val model = SplitAgreementViewModel(repo)
        model.load(memberDebtTask("original")); advanceUntilIdle()
        assertEquals("0.00", model.state.value.settlementInput)
        model.editDraft(reason = "保留原免除"); model.propose(); advanceUntilIdle()
        assertTrue(repo.commands.isEmpty())
        model.confirm(true); model.propose(); advanceUntilIdle()
        val create = requireNotNull(repo.commands.single().create)
        assertEquals(0L, create.settlementNetAmountCents)
        assertEquals(7L, create.expectedRowVersion)
        assertEquals(8L, create.expectedReturnRowVersion)
    }

    @Test fun pendingPaymentBlocksCreateAndAcceptButAllowsRejectWithoutSwallowingDraft() = runTest(dispatcher) {
        val repo = SplitProbe().apply { value = splitTestAgreement().copy(pendingRepaymentDebtPublicIds = listOf("return")) }
        val model = SplitAgreementViewModel(repo)
        model.load(memberDebtTask("original")); advanceUntilIdle()
        model.editDraft(reason = "保留原因"); model.confirm(true); model.propose(); advanceUntilIdle()
        assertTrue(repo.commands.isEmpty())
        repo.value = repo.value.copy(pendingProposal = splitTestProposal())
        model.refresh(); advanceUntilIdle(); model.confirm(true)
        model.resolve(true); advanceUntilIdle(); assertTrue(repo.commands.isEmpty())
        model.resolve(false); advanceUntilIdle()
        assertEquals("reject_bill_split_change_proposal", repo.commands.single().operation)
        assertEquals("保留原因", model.state.value.reason)
    }

    @Test fun returnTaskAcceptTargetsOriginalAndUsesBothCurrentVersions() = runTest(dispatcher) {
        val repo = SplitProbe().apply { value = splitTestAgreement().copy(pendingProposal = splitTestProposal()) }
        val model = SplitAgreementViewModel(repo)
        model.load(memberDebtTask("return")); advanceUntilIdle(); model.confirm(true)
        model.resolve(true); advanceUntilIdle()
        assertEquals("original", repo.submittedTask?.debtPublicId)
        assertEquals(SPLIT_ACCEPT, repo.commands.single().operation)
        assertEquals(8L, repo.commands.single().accept?.expectedReturnRowVersion)
    }

    @Test fun pendingProposalCanBeExplicitlyReplacedWithoutDroppingOfflineIntent() = runTest(dispatcher) {
        val proposal = splitTestProposal().copy(publicId = "proposal-to-replace")
        val repo = SplitProbe().apply { value = splitTestAgreement().copy(pendingProposal = proposal) }
        val model = SplitAgreementViewModel(repo)
        model.load(memberDebtTask("original")); advanceUntilIdle()

        model.editDraft(reason = "保留已付、返还和免除后重新约定")
        model.confirm(true)
        model.propose(); advanceUntilIdle()
        assertTrue(repo.commands.isEmpty(), "ordinary create remains blocked while a proposal is pending")

        model.beginReplacement()
        assertFalse(model.state.value.confirmed, "replacement selection requires a fresh settlement confirmation")
        model.confirm(true)
        assertTrue(model.state.value.canPropose)
        model.propose(); advanceUntilIdle()

        val create = requireNotNull(repo.commands.single().create)
        assertEquals("proposal-to-replace", create.supersedesProposalPublicId)
        assertEquals(2000L, create.newShareAmountCents)
        assertEquals(-1000L, create.settlementNetAmountCents)
        assertEquals(7L, create.expectedRowVersion)
        assertEquals(8L, create.expectedReturnRowVersion)
    }

    @Test fun changedPendingProposalInvalidatesReplacementChoiceButKeepsDraft() = runTest(dispatcher) {
        val repo = SplitProbe().apply { value = splitTestAgreement().copy(
            pendingProposal = splitTestProposal().copy(publicId = "proposal-old")) }
        val model = SplitAgreementViewModel(repo)
        model.load(memberDebtTask("original")); advanceUntilIdle()
        model.beginReplacement()
        model.editDraft(share = "12.00")
        model.editDraft(settlement = "-3.00")
        model.editDraft(reason = "保留这份替代草稿")

        repo.value = repo.value.copy(pendingProposal = splitTestProposal().copy(publicId = "proposal-new"))
        model.refresh(); advanceUntilIdle()

        assertEquals(null, model.state.value.replacingProposalPublicId)
        assertEquals("12.00", model.state.value.shareInput)
        assertEquals("-3.00", model.state.value.settlementInput)
        assertEquals("保留这份替代草稿", model.state.value.reason)
        model.confirm(true)
        model.propose(); advanceUntilIdle()
        assertTrue(repo.commands.isEmpty(), "the old replacement choice cannot target a different pending proposal")
    }

    @Test fun doneResolutionRefreshFailureBlocksDuplicateUntilCurrentAgreementRecovers() = runTest(dispatcher) {
        val repo = SplitProbe().apply { value = splitTestAgreement().copy(pendingProposal = splitTestProposal()) }
        val model = SplitAgreementViewModel(repo)
        val task = memberDebtTask("original")
        model.load(task); advanceUntilIdle()
        model.resolve(false); advanceUntilIdle()
        repo.fail = true
        repo.rows.value = listOf(OutboxRow(1, task.binding.serverUrl, task.binding.ledgerId,
            task.binding.ownerKey, PendingMutationType.SplitAgreement, "debt:original", "{}", 7,
            PendingMutationStatus.Done, 0, null, "2026-09-20", null, "2026-09-20", "key", "{}"))
        advanceUntilIdle()
        assertNotNull(model.state.value.error)
        assertEquals(UiText.res(R.string.split_agreement_submission_received), model.state.value.message)
        assertEquals(1L, model.state.value.acknowledgedRevision)
        assertFalse(model.state.value.agreementCurrent)
        model.resolve(false); advanceUntilIdle()
        assertEquals(1, repo.commands.size)
        assertNotNull(model.state.value.agreement)
        repo.fail = false
        repo.value = repo.value.copy(pendingProposal = splitTestProposal().copy(publicId = "proposal-new"))
        model.refresh(); advanceUntilIdle()
        assertTrue(model.state.value.agreementCurrent)
        model.resolve(false); advanceUntilIdle()
        assertEquals(2, repo.commands.size)
        assertEquals("proposal-new", repo.commands.last().proposalPublicId)
    }

    @Test fun droppingRestartedCreateRestoresItsDraftWhileUnknownIntentPreservesCurrentDraft() = runTest(dispatcher) {
        val repo = SplitProbe().apply { value = splitTestAgreement().copy(
            pendingProposal = splitTestProposal().copy(publicId = "proposal-new")) }
        val task = memberDebtTask("original")
        val row = OutboxRow(1, task.binding.serverUrl, task.binding.ledgerId,
            task.binding.ownerKey, PendingMutationType.SplitAgreement, "debt:original", "{}", 7,
            PendingMutationStatus.Conflict, 0, "state_conflict", "2026-09-20", null, "2026-09-20", "key", null)
        repo.intents[row.id] = SplitAgreementPayload(operation = SPLIT_CREATE,
            originalDebtPublicId = "original", returnDebtPublicId = "return",
            create = BillSplitChangeCreateRequestDto(1200, -300, "保留重启前草稿", 7, 8, "proposal-old"))
        repo.rows.value = listOf(row)
        val model = SplitAgreementViewModel(repo)
        model.load(task); advanceUntilIdle()
        assertEquals("20.00", model.state.value.shareInput)
        assertEquals("-10.00", model.state.value.settlementInput)
        assertEquals("", model.state.value.reason)

        model.recover(row, drop = true); advanceUntilIdle()
        assertEquals("12.00", model.state.value.shareInput)
        assertEquals("-3.00", model.state.value.settlementInput)
        assertEquals("保留重启前草稿", model.state.value.reason)
        assertEquals(null, model.state.value.replacingProposalPublicId)
        assertEquals(listOf(row.id to true), repo.recoveries)
        model.confirm(true); model.propose(); advanceUntilIdle()
        assertTrue(repo.commands.isEmpty(), "a restored old replacement draft cannot silently target the new proposal")

        val unknown = row.copy(id = 2, payloadJson = "unknown")
        repo.rows.value = listOf(unknown); advanceUntilIdle()
        model.editDraft(share = "15.00"); model.editDraft(settlement = "-4.00"); model.editDraft(reason = "当前另拟草稿")
        model.recover(unknown, drop = true); advanceUntilIdle()
        assertEquals(listOf(row.id to true, unknown.id to true), repo.recoveries)
        assertEquals("15.00", model.state.value.shareInput)
        assertEquals("-4.00", model.state.value.settlementInput)
        assertEquals("当前另拟草稿", model.state.value.reason)
    }

    @Test fun previousBindingDelayedReadCannotReplaceCurrentTask() = runTest(dispatcher) {
        val repo = SplitProbe()
        val model = SplitAgreementViewModel(repo)
        val first = memberDebtTask("original")
        repo.gate = CompletableDeferred()
        model.load(first); runCurrent()
        val oldGate = requireNotNull(repo.gate)
        repo.gate = null
        val next = first.copy(binding = first.binding.copy(ownerKey = "other"))
        model.load(next); advanceUntilIdle()
        oldGate.complete(Unit); advanceUntilIdle()
        assertEquals(next, model.state.value.task)
    }

    @Test fun nonParticipantCannotIssueAnyCommandAndSignedAmountsRespectCurrency() = runTest(dispatcher) {
        val repo = SplitProbe().apply { value = splitTestAgreement().copy(viewerIsParty = false, pendingProposal = splitTestProposal()) }
        val model = SplitAgreementViewModel(repo)
        model.load(memberDebtTask("original")); advanceUntilIdle(); model.confirm(true)
        model.propose(); model.resolve(true); model.resolve(false); advanceUntilIdle()
        assertTrue(repo.commands.isEmpty())
        assertFalse(model.state.value.canPropose)
        assertEquals(-123L, parseSplitSettlement("-1.23", CurrencyCode.CNY))
        assertEquals(-123L, parseSplitSettlement("-123", CurrencyCode.JPY))
        assertEquals(null, parseSplitSettlement("-1.23", CurrencyCode.JPY))
    }
}

private class SplitProbe : SplitAgreementActions {
    var value = splitTestAgreement()
    var fail = false
    var gate: CompletableDeferred<Unit>? = null
    val rows = MutableStateFlow<List<OutboxRow>>(emptyList())
    val intents = mutableMapOf<Long, SplitAgreementPayload>()
    val recoveries = mutableListOf<Pair<Long, Boolean>>()
    val commands = mutableListOf<SplitAgreementPayload>()
    var submittedTask: DebtTask? = null
    override suspend fun load(task: DebtTask, share: Long?): Result<BillSplitAgreementDto> {
        gate?.await()
        return if (fail) Result.failure(IOException("offline")) else Result.success(value.copy(
            preview = value.preview.copy(newShareAmountCents = share ?: value.agreedShareAmountCents)))
    }
    override suspend fun submit(task: DebtTask, intent: SplitAgreementPayload): Result<Long> {
        submittedTask = task; commands += intent
        return Result.success(1)
    }
    override fun describe(row: OutboxRow): SplitAgreementPayload? = intents[row.id]
    override fun observe(task: DebtTask) = rows
    override suspend fun recover(task: DebtTask, row: OutboxRow, drop: Boolean): Result<Unit> {
        recoveries += row.id to drop
        if (drop) rows.value = rows.value.filterNot { it.id == row.id }
        return Result.success(Unit)
    }
}
