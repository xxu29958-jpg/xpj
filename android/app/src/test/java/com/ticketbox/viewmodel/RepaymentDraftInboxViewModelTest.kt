package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.RepaymentDraftActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.RepaymentDraftStatuses
import com.ticketbox.domain.model.RepaymentNotificationDraft
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo)
        advanceUntilIdle()

        assertEquals(listOf("d1"), viewModel.state.value.drafts.map { it.publicId })
        // Only open + external/manual debts can take a direct repayment (mirrors guard_direct_fact_writable).
        assertEquals(listOf("open-external"), viewModel.state.value.targetDebts.map { it.publicId })
        assertEquals(false, viewModel.state.value.isLoading)
    }

    @Test
    fun refreshFailureSetsError() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(listResult = Result.failure(RuntimeException("offline")))
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions())
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions())
        advanceUntilIdle()
        val listCallsAfterInit = draftsRepo.listCalls

        viewModel.confirm("d1", debt("debt-9", rowVersion = 5L))
        advanceUntilIdle()

        val call = draftsRepo.confirmCalls.single()
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions())
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions())
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions())
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo)
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions())
        advanceUntilIdle()
        assertEquals("a", viewModel.state.value.drafts.single().publicId)

        draftsRepo.listResult = Result.success(listOf(draft("b")))
        viewModel.reload()
        assertTrue(viewModel.state.value.drafts.isEmpty()) // synchronous clear before the refetch
        advanceUntilIdle()

        assertEquals("b", viewModel.state.value.drafts.single().publicId)
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo)
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo)
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo)
        advanceUntilIdle()

        assertNull(viewModel.state.value.suggestedDebtByDraftId["d1"])
    }

    @Test
    fun dismissFlashClearsMessage() = runTest(dispatcher) {
        val draftsRepo = FakeRepaymentDraftActions(
            listResult = Result.success(listOf(draft("d1"))),
            dismissResult = Result.success(draft("d1", status = RepaymentDraftStatuses.DISMISSED)),
        )
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions())
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
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, debtsRepo)
        advanceUntilIdle()
        assertEquals(1L, viewModel.state.value.targetDebts.single().rowVersion)

        // A slow refresh stalls having captured the rv1 debt snapshot...
        val gate = CompletableDeferred<Unit>()
        debtsRepo.listGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then a repayment elsewhere bumps the row_version; a newer refresh picks up rv2.
        debtsRepo.listGate = null
        debtsRepo.listResult = Result.success(listOf(debt("card", rowVersion = 2L)))
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals(2L, viewModel.state.value.targetDebts.single().rowVersion)

        // Release the stale refresh; the stale rv1 must NOT come back as the OCC token.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(2L, viewModel.state.value.targetDebts.single().rowVersion)
    }

    @Test
    fun staleRefreshDoesNotClobberReloadedLedger() = runTest(dispatcher) {
        // Ledger switch: a slow prior refresh must not show the old ledger's drafts under the new one.
        val draftsRepo = FakeRepaymentDraftActions(listResult = Result.success(listOf(draft("ledgerA"))))
        val viewModel = RepaymentDraftInboxViewModel(draftsRepo, FakeRepayableDebtActions())
        advanceUntilIdle()

        // A slow refresh stalls (it captured ledger A's drafts)...
        val gate = CompletableDeferred<Unit>()
        draftsRepo.listGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then a ledger switch reloads with ledger B's drafts.
        draftsRepo.listGate = null
        draftsRepo.listResult = Result.success(listOf(draft("ledgerB")))
        viewModel.reload()
        advanceUntilIdle()
        assertEquals("ledgerB", viewModel.state.value.drafts.single().publicId)

        // Release the stale refresh; ledger A's drafts must NOT leak back under ledger B.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals("ledgerB", viewModel.state.value.drafts.single().publicId)
        assertEquals(false, viewModel.state.value.isLoading)
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
    val dismissCalls = mutableListOf<String>()

    /** When set, listPendingDrafts() stalls until completed — used to interleave a slow load. */
    var listGate: CompletableDeferred<Unit>? = null

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun createDraft(
        draft: RepaymentNotificationDraft,
        expectedLedgerId: String?,
        notificationKey: String?,
    ): Result<RepaymentDraft> = Result.success(draft("created"))

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
    ): Result<RepaymentDraft> {
        confirmCalls += ConfirmCall(draftPublicId, targetDebtPublicId, expectedRowVersion)
        return confirmResult
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
    override suspend fun listDebts(): Result<List<Debt>> {
        // Capture at entry so a stalled load returns the snapshot it started with.
        val captured = listResult
        listGate?.await()
        return captured
    }
    override suspend fun getDebt(publicId: String): Result<Debt> = Result.success(debt(publicId))
    override suspend fun createDebt(draft: DebtDraft): Result<Debt> = Result.success(debt("created"))
    override suspend fun recordRepayment(publicId: String, expectedRowVersion: Long, amountCents: Long): Result<Debt> =
        Result.success(debt(publicId))

    override suspend fun recordAdjustment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
        reason: String,
    ): Result<Debt> = Result.success(debt(publicId))

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
