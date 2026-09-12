package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtAdjustmentFixture
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.data.repository.RepaymentDraftActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.RepaymentDraftStatuses
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
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

@OptIn(ExperimentalCoroutinesApi::class)
class RepaymentDraftInboxViewModelTest {

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
    fun initLoadsPendingDraftsAndOnlyRepayableDebts() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(listResult = Result.success(listOf(draft("d1"))))
        val debtsRepo = FakeRepayableDebtActions(
            listResult = Result.success(
                listOf(
                    debt("open-external", status = DebtLinkStatuses.OPEN, counterparty = DebtCounterpartyTypes.EXTERNAL),
                    debt("cleared", status = DebtLinkStatuses.CLEARED, counterparty = DebtCounterpartyTypes.EXTERNAL),
                    debt("member", status = DebtLinkStatuses.OPEN, counterparty = DebtCounterpartyTypes.MEMBER),
                    debt("bill-split", status = DebtLinkStatuses.OPEN, source = DebtSourceTypes.BILL_SPLIT),
                ),
            ),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo, writes = FakeDebtWriteActions())
        advanceUntilIdle()

        assertEquals(listOf("d1"), viewModel.state.value.drafts.map { it.publicId })
        // Only open + external/manual debts can take a direct repayment (mirrors guard_direct_fact_writable).
        assertEquals(listOf("open-external"), viewModel.state.value.targetDebts.map { it.publicId })
        assertEquals(false, viewModel.state.value.isLoading)
    }

    @Test
    fun unresolvedAdjustmentsExcludeSuggestedAndManualRepaymentTargets() = runTest(dispatcher) {
        for (status in listOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight,
            PendingMutationStatus.Failed, PendingMutationStatus.Conflict)) {
            val writes = DebtAdjustmentFixture()
            val id = writes.save().getOrThrow()
            val original = writes.dao.rows.getValue(id).copy(status = status.wireValue)
            writes.dao.rows[id] = original
            val blocked = writes.debt
            val available = debt("unrelated-debt", rowVersion = 9L)
            val pendingDraft = draft("draft-1", suggestedDebtPublicId = blocked.publicId)
            val drafts = FakeRepaymentDraftActions(listResult = Result.success(listOf(pendingDraft)))
            val model = RepaymentDraftInboxViewModel(drafts,
                FakeRepayableDebtActions(listResult = Result.success(listOf(blocked, available))), writes.repository)
            try {
                advanceUntilIdle()
                assertEquals(listOf(pendingDraft), model.state.value.drafts)
                assertEquals(listOf(available), model.state.value.targetDebts, status.toString())
                assertNull(model.state.value.suggestedDebtByDraftId[pendingDraft.publicId])
                model.confirm(pendingDraft.publicId, blocked)
                advanceUntilIdle()
                assertTrue(drafts.confirmCalls.isEmpty())
                assertNull(model.state.value.flashMessage)
                assertEquals(original, writes.dao.rows.getValue(id))
                assertTrue(writes.api.calls.isEmpty())
            } finally {
                model.viewModelScope.cancel()
            }
        }
    }

    @Test
    fun previouslySelectedRepaymentTargetCannotRaceANewUnresolvedAdjustment() = runTest(dispatcher) {
        val writes = DebtAdjustmentFixture()
        val blocked = writes.debt
        val available = debt("unrelated-debt", rowVersion = 9L)
        val pendingDraft = draft("draft-1", suggestedDebtPublicId = blocked.publicId)
        val drafts = FakeRepaymentDraftActions(listResult = Result.success(listOf(pendingDraft)))
        val model = RepaymentDraftInboxViewModel(drafts,
            FakeRepayableDebtActions(listResult = Result.success(listOf(blocked, available))), writes.repository)
        try {
            advanceUntilIdle()
            val selected = model.state.value.suggestedDebtByDraftId.getValue(pendingDraft.publicId)
            assertEquals(2L, selected.rowVersion)
            val id = writes.save().getOrThrow()
            val original = writes.dao.rows.getValue(id)
            // The picker already holds this Debt. Do not deliver the next Room notification first.
            model.confirm(pendingDraft.publicId, selected)
            advanceUntilIdle()
            assertTrue(drafts.confirmCalls.isEmpty())
            assertEquals(listOf(pendingDraft), model.state.value.drafts)
            assertNull(model.state.value.flashMessage)
            assertEquals(original, writes.dao.rows.getValue(id))
            assertEquals(listOf(available), model.state.value.targetDebts)

            model.confirm(pendingDraft.publicId, available)
            advanceUntilIdle()
            assertEquals(listOf(ConfirmCall(pendingDraft.publicId, available.publicId, 9L)), drafts.confirmCalls)
            assertEquals(original, writes.dao.rows.getValue(id))
            assertTrue(writes.api.calls.isEmpty())
        } finally {
            model.viewModelScope.cancel()
        }
    }

    @Test
    fun draftsAndTargetDebtsCarryRecordHomeCurrencyForDisplayLens() = runTest(dispatcher) {
        // PR#255 R5 P1：草稿行金额与选债面板 remaining 走 CurrencyDisplay.forRecord(
        // record.homeCurrencyCode) —— 钉死 VM 数据通路：两类 record 的 homeCurrencyCode
        // 原样留在 state（JPY 不被恒 Base 的环境 display 覆盖）。
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(listOf(draft("d1").copy(homeCurrencyCode = "JPY"))),
        )
        val debtsRepo = FakeRepayableDebtActions(
            listResult = Result.success(listOf(debt("open-external").copy(homeCurrencyCode = "JPY"))),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo, writes = FakeDebtWriteActions())
        advanceUntilIdle()

        assertEquals("JPY", viewModel.state.value.drafts.single().homeCurrencyCode)
        assertEquals("JPY", viewModel.state.value.targetDebts.single().homeCurrencyCode)
    }

    @Test
    fun refreshFailureSetsError() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(listResult = Result.failure(RuntimeException("offline")))
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions(), writes = FakeDebtWriteActions())
        advanceUntilIdle()

        assertTrue(viewModel.state.value.drafts.isEmpty())
        assertTrue(viewModel.state.value.error != null)
    }

    @Test
    fun confirmRecordsAgainstChosenDebtThenFlashesAndRefetches() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(listOf(draft("d1"))),
            confirmResult = Result.success(draft("d1", status = RepaymentDraftStatuses.CONFIRMED)),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo,
            FakeRepayableDebtActions(listResult = Result.success(listOf(debt("debt-9", rowVersion = 5L)))),
            writes = FakeDebtWriteActions())
        advanceUntilIdle()
        val listCallsAfterInit = draftsRepo.listCalls

        viewModel.confirm("d1", debt("debt-9", rowVersion = 5L))
        advanceUntilIdle()

        val call = draftsRepo.confirmCalls.single()
        assertEquals(adjustmentBinding(), draftsRepo.confirmBindings.single())
        assertEquals("d1", call.draftPublicId)
        assertEquals("debt-9", call.targetDebtPublicId)
        // The chosen Debt's row_version is the §2.1 OCC token.
        assertEquals(5L, call.expectedRowVersion)
        assertTrue(viewModel.state.value.flashMessage != null)
        assertNull(viewModel.state.value.pendingActionDraftId)
        assertTrue(draftsRepo.listCalls > listCallsAfterInit) // re-fetched
    }

    @Test
    fun confirmFailureSetsErrorAndClearsBusy() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(listOf(draft("d1"))),
            confirmResult = Result.failure(RuntimeException("409")),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo,
            FakeRepayableDebtActions(listResult = Result.success(listOf(debt("debt-9", rowVersion = 1L)))),
            writes = FakeDebtWriteActions())
        advanceUntilIdle()

        viewModel.confirm("d1", debt("debt-9", rowVersion = 1L))
        advanceUntilIdle()

        assertTrue(viewModel.state.value.error != null)
        assertNull(viewModel.state.value.pendingActionDraftId)
        assertNull(viewModel.state.value.flashMessage)
    }

    @Test
    fun dismissResolvesThenFlashesAndRefetches() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(listOf(draft("d1"))),
            dismissResult = Result.success(draft("d1", status = RepaymentDraftStatuses.DISMISSED)),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions(), writes = FakeDebtWriteActions())
        advanceUntilIdle()
        val listCallsAfterInit = draftsRepo.listCalls

        viewModel.dismiss("d1")
        advanceUntilIdle()

        assertEquals(listOf("d1"), draftsRepo.dismissCalls)
        assertTrue(viewModel.state.value.flashMessage != null)
        assertTrue(draftsRepo.listCalls > listCallsAfterInit)
    }

    @Test
    fun secondActionIgnoredWhileOneInFlight() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(listOf(draft("d1"), draft("d2"))),
            confirmResult = Result.success(draft("d1", status = RepaymentDraftStatuses.CONFIRMED)),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo,
            FakeRepayableDebtActions(listResult = Result.success(listOf(debt("debt-9", rowVersion = 1L)))),
            writes = FakeDebtWriteActions())
        advanceUntilIdle()

        // Two actions fired back-to-back before the first settles: the second must be dropped
        // (pendingActionDraftId gate) so a stale double-tap can't double-record.
        viewModel.confirm("d1", debt("debt-9", rowVersion = 1L))
        viewModel.dismiss("d2")
        advanceUntilIdle()

        assertEquals(1, draftsRepo.confirmCalls.size)
        assertTrue(draftsRepo.dismissCalls.isEmpty())
    }

    @Test
    fun partialDebtFetchFailureClearsTargetDebtsAndSurfacesError() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(listResult = Result.success(listOf(draft("d1"))))
        val debtsRepo = FakeRepayableDebtActions(listResult = Result.success(listOf(debt("open-external"))))
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo, writes = FakeDebtWriteActions())
        advanceUntilIdle()
        assertEquals(listOf("open-external"), viewModel.state.value.targetDebts.map { it.publicId })

        // draft 仍成功、debt 拉取瞬时失败:候选必须被**清空**(不留陈旧 rowVersion 致下次 confirm 必 409)并报错。
        debtsRepo.listResult = Result.failure(RuntimeException("offline"))
        viewModel.refresh()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.targetDebts.isEmpty())
        assertTrue(viewModel.state.value.error != null)
        assertEquals(listOf("d1"), viewModel.state.value.drafts.map { it.publicId }) // drafts 不受影响
    }

    @Test
    fun reloadClearsPriorLedgerStateThenRefetches() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(listResult = Result.success(listOf(draft("a"))))
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions(), writes = FakeDebtWriteActions())
        advanceUntilIdle()
        assertEquals("a", viewModel.state.value.drafts.single().publicId)

        draftsRepo.listResult = Result.success(listOf(draft("b")))
        viewModel.reload()
        assertTrue(viewModel.state.value.drafts.isEmpty()) // synchronous clear before the refetch
        advanceUntilIdle()

        assertEquals("b", viewModel.state.value.drafts.single().publicId)
    }

    @Test
    fun reloadWithFocusedDraftPinsItFirst() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(
                listOf(
                    draft("old-a"),
                    draft("from-expense", suggestedDebtPublicId = "card"),
                    draft("old-b"),
                ),
            ),
        )
        val debtsRepo = FakeRepayableDebtActions(
            listResult = Result.success(listOf(debt("card"))),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo, writes = FakeDebtWriteActions())
        advanceUntilIdle()

        viewModel.reload(focusedDraftPublicId = "from-expense")
        advanceUntilIdle()

        assertEquals(
            listOf("from-expense", "old-a", "old-b"),
            viewModel.state.value.drafts.map { it.publicId },
        )
        assertEquals("from-expense", viewModel.state.value.focusedDraftPublicId)
        assertEquals("card", viewModel.state.value.suggestedDebtByDraftId["from-expense"]?.publicId)
    }

    @Test
    fun suggestionResolvesToFeasibleRepayableDebtWithLocalRowVersion() = runTest(dispatcher) {
        // §杠杆③ 3b: the server suggests a Debt by public_id; the VM resolves it against the local
        // repayable list so the row_version (the §2.1 OCC token) comes from the same fetch.
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(listOf(draft("d1", suggestedDebtPublicId = "card"))),
        )
        val debtsRepo = FakeRepayableDebtActions(
            // default remaining 50_000 ≥ draft amount 50_000 → feasible.
            listResult = Result.success(listOf(debt("card", rowVersion = 3L))),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo, writes = FakeDebtWriteActions())
        advanceUntilIdle()

        val suggested = viewModel.state.value.suggestedDebtByDraftId["d1"]
        assertEquals("card", suggested?.publicId)
        assertEquals(3L, suggested?.rowVersion)

        // Mirror the screen's one-tap "确认还到" wiring (onConfirmSuggested → confirm(draft, suggested)):
        // the confirm must carry the resolved suggestion's publicId AND its local-list row_version as
        // the §2.1 OCC token — closing the seam between "resolves correctly" and "confirms what it resolved".
        viewModel.confirm("d1", suggested!!)
        advanceUntilIdle()
        val call = draftsRepo.confirmCalls.single()
        assertEquals("card", call.targetDebtPublicId)
        assertEquals(3L, call.expectedRowVersion)
    }

    @Test
    fun suggestionDroppedWhenSuggestedDebtCannotAbsorbAmount() = runTest(dispatcher) {
        // The local remaining is below the draft amount (a repayment landed between the two
        // fetches): drop the suggestion rather than pre-select one that would 422 on confirm.
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(listOf(draft("d1", suggestedDebtPublicId = "card"))), // amount 50_000
        )
        val debtsRepo = FakeRepayableDebtActions(
            listResult = Result.success(listOf(debt("card").copy(remainingAmountCents = 10_000))),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo, writes = FakeDebtWriteActions())
        advanceUntilIdle()

        assertNull(viewModel.state.value.suggestedDebtByDraftId["d1"])
    }

    @Test
    fun suggestionDroppedWhenSuggestedDebtMissingFromRepayableList() = runTest(dispatcher) {
        // The server suggested a Debt the client's own debt fetch doesn't include (cleared between
        // fetches, or filtered out): no pre-selection — the user picks manually.
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(listOf(draft("d1", suggestedDebtPublicId = "gone"))),
        )
        val debtsRepo = FakeRepayableDebtActions(
            listResult = Result.success(listOf(debt("other"))),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo, writes = FakeDebtWriteActions())
        advanceUntilIdle()

        assertNull(viewModel.state.value.suggestedDebtByDraftId["d1"])
    }

    @Test
    fun dismissFlashClearsMessage() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(listOf(draft("d1"))),
            dismissResult = Result.success(draft("d1", status = RepaymentDraftStatuses.DISMISSED)),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions(), writes = FakeDebtWriteActions())
        advanceUntilIdle()
        viewModel.dismiss("d1")
        advanceUntilIdle()
        assertTrue(viewModel.state.value.flashMessage != null)

        viewModel.dismissFlash()

        assertNull(viewModel.state.value.flashMessage)
    }

    // ── ADR-0049 §2.1 stale-refresh 代际守卫（功能正确性加固 #2，镜像 DebtListViewModel）─────────────

    @Test
    fun staleRefreshDoesNotReviveStaleTargetDebtRowVersion() = runTest(dispatcher) {
        // The §2.1 OCC hazard: targetDebts carry the row_version confirm() sends. A slow refresh that
        // captured an old row_version must not revive it over a newer fetch's bumped version — else
        // the next confirm sends a stale OCC token → a deterministic 409.
        val draftsRepo = FakeRepaymentDraftActions(listResult = Result.success(listOf(draft("d1"))))
        val debtsRepo = FakeRepayableDebtActions(listResult = Result.success(listOf(debt("card", rowVersion = 1L))))
        val writes = FakeDebtWriteActions()
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo, writes)
        advanceUntilIdle()
        assertEquals(1L, viewModel.state.value.targetDebts.single().rowVersion)
        val originalChoice = viewModel.state.value.targetDebts.single()

        // A slow refresh stalls having captured the rv1 debt snapshot...
        val gate = CompletableDeferred<Unit>()
        debtsRepo.listGate = gate
        writes.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.Done))
        runCurrent()
        assertTrue(viewModel.state.value.isLoading)
        assertTrue(viewModel.state.value.targetDebts.isEmpty())
        viewModel.confirm("d1", originalChoice)
        runCurrent()
        assertTrue(draftsRepo.confirmCalls.isEmpty())

        // ...then a repayment elsewhere bumps the row_version; a newer refresh picks up rv2.
        debtsRepo.listGate = null
        debtsRepo.listResult = Result.success(listOf(debt("card", rowVersion = 2L)))
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals(2L, viewModel.state.value.targetDebts.single().rowVersion)

        viewModel.confirm("d1", originalChoice)
        advanceUntilIdle()
        assertTrue(draftsRepo.confirmCalls.isEmpty(), "An old picker callback cannot silently borrow fresh OCC")
        viewModel.confirm("d1", viewModel.state.value.targetDebts.single())
        advanceUntilIdle()
        assertEquals(2L, draftsRepo.confirmCalls.single().expectedRowVersion)

        // Release the stale refresh; the stale rv1 must NOT come back as the OCC token.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(2L, viewModel.state.value.targetDebts.single().rowVersion)
    }

    @Test
    fun staleRefreshDoesNotClobberReloadedLedger() = runTest(dispatcher) {
        // Ledger switch: a slow prior refresh must not show the old ledger's drafts under the new one.
        val draftsRepo = FakeRepaymentDraftActions(listResult = Result.success(listOf(draft("ledgerA"))))
        val target = debt("debt-a", rowVersion = 5L)
        val debtsRepo = FakeRepayableDebtActions(listResult = Result.success(listOf(target)))
        val writes = FakeDebtWriteActions()
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo, writes)
        advanceUntilIdle()
        val confirmGate = CompletableDeferred<Unit>()
        draftsRepo.confirmGate = confirmGate
        viewModel.confirm("ledgerA", target)
        runCurrent()
        assertEquals(ConfirmCall("ledgerA", "debt-a", 5L), draftsRepo.confirmCalls.single())
        assertEquals(adjustmentBinding(), draftsRepo.confirmBindings.single())
        assertEquals("ledgerA", viewModel.state.value.pendingActionDraftId)

        // A slow refresh stalls (it captured ledger A's drafts)...
        val gate = CompletableDeferred<Unit>()
        draftsRepo.listGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then a ledger switch reloads with ledger B's drafts.
        draftsRepo.listGate = null
        draftsRepo.listResult = Result.success(listOf(draft("ledgerB")))
        debtsRepo.listResult = Result.success(emptyList())
        writes.access.value = com.ticketbox.data.repository.LedgerAccessContext(
            adjustmentBinding().copy(ledgerId = "ledger-b", bindingRevision = "binding-b"), canModify = true,
        )
        advanceUntilIdle()
        assertEquals("ledgerB", viewModel.state.value.drafts.single().publicId)
        assertNull(viewModel.state.value.pendingActionDraftId)

        // Neither a stale read nor a late successful write may publish into the replacement binding.
        gate.complete(Unit)
        confirmGate.complete(Unit)
        advanceUntilIdle()
        assertEquals("ledgerB", viewModel.state.value.drafts.single().publicId)
        assertEquals(false, viewModel.state.value.isLoading)
        assertNull(viewModel.state.value.flashMessage)
        assertNull(viewModel.state.value.pendingActionDraftId)
        viewModel.viewModelScope.cancel()
    }
}

private data class ConfirmCall(val draftPublicId: String, val targetDebtPublicId: String, val expectedRowVersion: Long)

private class FakeRepaymentDraftActions(
    private val canModify: Boolean = true,
    var listResult: Result<List<RepaymentDraft>> = Result.success(emptyList()),
    var confirmResult: Result<RepaymentDraft> = Result.success(draft("d1", status = RepaymentDraftStatuses.CONFIRMED)),
    var dismissResult: Result<RepaymentDraft> = Result.success(draft("d1", status = RepaymentDraftStatuses.DISMISSED)),
) : RepaymentDraftActions {
    var listCalls = 0
    val confirmCalls = mutableListOf<ConfirmCall>()
    val confirmBindings = mutableListOf<com.ticketbox.data.repository.LogicalSessionBinding>()
    val dismissCalls = mutableListOf<String>()

    /** When set, listPendingDrafts() stalls until completed — used to interleave a slow load. */
    var listGate: CompletableDeferred<Unit>? = null
    var confirmGate: CompletableDeferred<Unit>? = null

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun listPendingDrafts(): Result<List<RepaymentDraft>> {
        listCalls++
        // Capture at entry so a stalled load returns the snapshot it started with.
        val captured = listResult
        listGate?.await()
        return captured
    }

    override suspend fun confirmDraft(
        draftPublicId: String,
        targetDebtPublicId: String,
        expectedRowVersion: Long,
        expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding,
    ): Result<RepaymentDraft> {
        confirmCalls += ConfirmCall(draftPublicId, targetDebtPublicId, expectedRowVersion)
        confirmBindings += expectedBinding
        val captured = confirmResult
        confirmGate?.await()
        return captured
    }

    override suspend fun dismissDraft(draftPublicId: String): Result<RepaymentDraft> {
        dismissCalls += draftPublicId
        return dismissResult
    }
}

private class FakeRepayableDebtActions(
    private val canModify: Boolean = true,
    var listResult: Result<List<Debt>> = Result.success(emptyList()),
) : DebtActions {
    /** When set, listDebts() stalls until completed — used to interleave a slow load. */
    var listGate: CompletableDeferred<Unit>? = null

    override fun canModifyLedger(): Boolean = canModify
    override suspend fun listDebts(lens: com.ticketbox.domain.model.DebtListLens): Result<DebtListPage> {
        // Capture at entry so a stalled load returns the snapshot it started with.
        val captured = listResult
        listGate?.await()
        return captured.map { DebtListPage(debts = it, ledgerHomeCurrencyCode = null) }
    }
    override suspend fun getDebt(publicId: String): Result<Debt> = Result.success(debt(publicId))
    override suspend fun parseDebtBillImage(
        expectedBinding: LogicalSessionBinding,
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
    ): Result<DebtBillSuggestion> = Result.failure(UnsupportedOperationException())

    override suspend fun voidRepayment(
        publicId: String,
        repaymentPublicId: String,
        expectedRowVersion: Long,
        reason: String,
    ): Result<Debt> = Result.failure(UnsupportedOperationException())

    override suspend fun voidDebt(publicId: String, expectedRowVersion: Long, reason: String): Result<Debt> =
        Result.success(debt(publicId))

    override suspend fun setDebtKind(publicId: String, expectedRowVersion: Long, debtKind: String): Result<Debt> =
        Result.success(debt(publicId))
}

private fun draft(
    publicId: String,
    status: String = RepaymentDraftStatuses.PENDING,
    suggestedDebtPublicId: String? = null,
): RepaymentDraft = RepaymentDraft(
    publicId = publicId,
    source = "alipay",
    amountCents = 50_000,
    homeCurrencyCode = "CNY",
    merchantLabel = "花呗",
    capturedAt = "2026-06-17T08:00:00Z",
    status = status,
    suggestedDebtPublicId = suggestedDebtPublicId,
    committedDebtPublicId = null,
    committedRepaymentPublicId = null,
    createdAt = "2026-06-17T08:00:01Z",
    resolvedAt = null,
)

private fun debt(
    publicId: String,
    status: String = DebtLinkStatuses.OPEN,
    counterparty: String = DebtCounterpartyTypes.EXTERNAL,
    source: String = DebtSourceTypes.MANUAL,
    rowVersion: Long = 1L,
): Debt = Debt(
    publicId = publicId,
    ledgerId = "owner",
    direction = DebtDirections.I_OWE,
    counterpartyType = counterparty,
    counterpartyAccountId = null,
    counterpartyLabel = "房东",
    principalAmountCents = 50_000,
    remainingAmountCents = 50_000,
    paidAmountCents = 0,
    status = status,
    sourceType = source,
    sourceId = null,
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-15T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = rowVersion,
)
