package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.DebtLinkStatuses
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

class DebtListViewModelTest {

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
    fun initLoadsDebtsAndReflectsRole() = runTest(dispatcher) {
        val repo = FakeDebtActions(canModify = false, listResult = Result.success(listOf(sampleDebt())))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals(1, viewModel.state.value.debts.size)
        assertEquals(false, viewModel.state.value.canModify)
        assertEquals(false, viewModel.state.value.isLoading)
    }

    @Test
    fun refreshFailureSetsError() = runTest(dispatcher) {
        val repo = FakeDebtActions(listResult = Result.failure(RuntimeException("offline")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.debts.isEmpty())
        assertTrue(viewModel.state.value.error != null)
    }

    @Test
    fun submitDraftCreatesThenResetsFlashesAndRefetches() = runTest(dispatcher) {
        val repo = FakeDebtActions(createResult = Result.success(sampleDebt("created")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()
        val listCallsAfterInit = repo.listCalls

        viewModel.updateDraftDirection(DebtDirections.OWED_TO_ME)
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("123.45")
        viewModel.submitDraft()
        advanceUntilIdle()

        val draft = repo.createDrafts.single()
        assertEquals(DebtDirections.OWED_TO_ME, draft.direction)
        assertEquals("小王", draft.counterpartyLabel)
        assertEquals(12_345L, draft.principalAmountCents)
        // Success → draft reset, flash shown, list re-fetched.
        assertEquals("", viewModel.state.value.addDraft.counterpartyLabel)
        assertTrue(viewModel.state.value.flashMessage != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
        assertTrue(repo.listCalls > listCallsAfterInit)
    }

    @Test
    fun submitDraftCarriesSelectedKind() = runTest(dispatcher) {
        // 8e-6e: the create form's kind picker flows into the DebtDraft (default unspecified → picked).
        val repo = FakeDebtActions(createResult = Result.success(sampleDebt("created")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.updateDraftKind(DebtKinds.INSTALLMENT)
        viewModel.submitDraft()
        advanceUntilIdle()

        assertEquals(DebtKinds.INSTALLMENT, repo.createDrafts.single().debtKind)
    }

    @Test
    fun submitDraftCarriesInstallmentCountForInstallmentKind() = runTest(dispatcher) {
        // §B: the parsed 分期期数 flows into the DebtDraft (the toCreateRequest chokepoint then gates it
        // on kind — covered in DebtMappersTest); here we只验证 VM 把 parsedInstallmentCount 接进了草稿。
        val repo = FakeDebtActions(createResult = Result.success(sampleDebt("created")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("花呗")
        viewModel.updateDraftAmount("1200")
        viewModel.updateDraftKind(DebtKinds.INSTALLMENT)
        viewModel.updateDraftInstallmentCount("12")
        viewModel.updateDraftInstallmentPeriod("3")
        viewModel.submitDraft()
        advanceUntilIdle()

        val draft = repo.createDrafts.single()
        assertEquals(DebtKinds.INSTALLMENT, draft.debtKind)
        assertEquals(12, draft.installmentCount)
        assertEquals(3, draft.installmentPeriodMonths)
    }

    @Test
    fun submitDraftDefaultsKindToUnspecified() = runTest(dispatcher) {
        // No kind picked → the draft carries the default (unspecified) so an untouched form still creates.
        val repo = FakeDebtActions(createResult = Result.success(sampleDebt("created")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertEquals(DebtKinds.UNSPECIFIED, repo.createDrafts.single().debtKind)
    }

    @Test
    fun updateCounterpartyInheritsExistingTargetModel() = runTest(dispatcher) {
        val existing = sampleDebt("huabei").copy(
            counterpartyLabel = "花呗",
            debtKind = DebtKinds.INSTALLMENT,
            installmentCount = 12,
            installmentPeriodMonths = 1,
        )
        val repo = FakeDebtActions(listResult = Result.success(listOf(existing)))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty(" 花 呗 ")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()

        val draft = repo.createDrafts.single()
        assertEquals(DebtKinds.INSTALLMENT, draft.debtKind)
        assertEquals(12, draft.installmentCount)
        assertEquals(1, draft.installmentPeriodMonths)
    }

    @Test
    fun ambiguousExistingTargetModelsDoNotAutoInherit() = runTest(dispatcher) {
        val debts = listOf(
            sampleDebt("one").copy(counterpartyLabel = "信用卡", debtKind = DebtKinds.REVOLVING),
            sampleDebt("two").copy(counterpartyLabel = "信用卡", debtKind = DebtKinds.INSTALLMENT, installmentCount = 12),
        )
        val repo = FakeDebtActions(listResult = Result.success(debts))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("信用卡")

        assertEquals(DebtKinds.UNSPECIFIED, viewModel.state.value.addDraft.kind)
    }

    @Test
    fun parseDebtBillPrefillsDraftAndRequestsSheetOpen() = runTest(dispatcher) {
        val repo = FakeDebtActions(
            parseBillResult = Result.success(
                DebtBillSuggestion(
                    merchant = "花呗",
                    principalAmountCents = 120_000,
                    installmentCount = 12,
                    installmentPeriodMonths = 1,
                    perPeriodAmountCents = 10_000,
                    repaymentDay = 10,
                    sourceText = "花呗 分期 12期",
                    confidence = 0.8,
                ),
            ),
        )
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertTrue(viewModel.markBillParsePreparing())
        viewModel.parseDebtBillImage("bill.jpg", "image/jpeg", byteArrayOf(1, 2, 3))
        advanceUntilIdle()

        val draft = viewModel.state.value.addDraft
        assertEquals(listOf("bill.jpg"), repo.parseBillCalls)
        assertEquals("花呗", draft.counterpartyLabel)
        assertEquals("1200", draft.amountYuanInput)
        assertEquals(DebtKinds.INSTALLMENT, draft.kind)
        assertEquals("12", draft.installmentCountInput)
        assertEquals("1", draft.installmentPeriodInput)
        assertEquals(false, viewModel.state.value.isParsingBill)
        assertTrue(viewModel.state.value.pendingBillParsePrefill)
        viewModel.ackBillParsePrefill()
        assertEquals(false, viewModel.state.value.pendingBillParsePrefill)
    }

    @Test
    fun submitDraftWithBlankCounterpartyShowsValidationWithoutCreate() = runTest(dispatcher) {
        val repo = FakeDebtActions()
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.addDraft.validationError != null)
        assertTrue(repo.createDrafts.isEmpty())
    }

    @Test
    fun submitDraftWithNonPositiveAmountShowsValidationWithoutCreate() = runTest(dispatcher) {
        val repo = FakeDebtActions()
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        // Valid counterparty but a non-positive amount → the amount arm of the submit guard.
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("0")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.addDraft.validationError != null)
        assertTrue(repo.createDrafts.isEmpty())
    }

    @Test
    fun submitDraftFailureKeepsFormWithError() = runTest(dispatcher) {
        val repo = FakeDebtActions(createResult = Result.failure(RuntimeException("boom")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.addDraft.validationError != null)
        // The form retains the user's input so they can retry, not wiped.
        assertEquals("小王", viewModel.state.value.addDraft.counterpartyLabel)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun submitDraftSuccessSetsAddSucceededThenResetClears() = runTest(dispatcher) {
        // The one-shot success signal is what drives the sheet to close — set ONLY on a real
        // create success, then cleared by resetDraft when the screen closes (mirrors the
        // LedgerViewModel.manualCreateDone ack convention).
        val repo = FakeDebtActions(createResult = Result.success(sampleDebt("created")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.addSucceeded)
        viewModel.resetDraft()
        assertEquals(false, viewModel.state.value.addSucceeded)
    }

    @Test
    fun submitDraftFailureLeavesAddSucceededFalse() = runTest(dispatcher) {
        // A server failure must NOT signal the screen to close — the sheet stays open with its
        // error instead of vanishing while the debt was silently not created (the fixed bug).
        val repo = FakeDebtActions(createResult = Result.failure(RuntimeException("boom")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertEquals(false, viewModel.state.value.addSucceeded)
    }

    @Test
    fun resetDraftClearsInput() = runTest(dispatcher) {
        val repo = FakeDebtActions()
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.resetDraft()

        assertEquals("", viewModel.state.value.addDraft.counterpartyLabel)
        assertEquals("", viewModel.state.value.addDraft.amountYuanInput)
    }

    @Test
    fun dismissFlashClearsMessage() = runTest(dispatcher) {
        val repo = FakeDebtActions(createResult = Result.success(sampleDebt("created")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(viewModel.state.value.flashMessage != null)

        viewModel.dismissFlash()

        assertNull(viewModel.state.value.flashMessage)
    }

    @Test
    fun reloadClearsPriorLedgerDebtsThenRefetches() = runTest(dispatcher) {
        val repo = FakeDebtActions(listResult = Result.success(listOf(sampleDebt("a"))))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()
        assertEquals("a", viewModel.state.value.debts.single().publicId)

        // Simulate a ledger switch: the cached VM must not show the old ledger's debts.
        repo.listResult = Result.success(listOf(sampleDebt("b")))
        viewModel.reload()
        assertTrue(viewModel.state.value.debts.isEmpty()) // synchronous clear before the refetch
        advanceUntilIdle()

        assertEquals("b", viewModel.state.value.debts.single().publicId)
    }

    @Test
    fun staleRefreshDoesNotRevertAfterCreate() = runTest(dispatcher) {
        // A slow earlier refresh must not blank out the list after the user just added a debt.
        val repo = FakeDebtActions(
            listResult = Result.success(emptyList()),
            createResult = Result.success(sampleDebt("new")),
        )
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle() // init refresh → debts = []

        // A slow refresh stalls inside listDebts() (it captured the pre-create empty list)...
        val gate = CompletableDeferred<Unit>()
        repo.listGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then the user creates a debt; submitDraft's success refresh delivers the new list.
        repo.listGate = null
        repo.listResult = Result.success(listOf(sampleDebt("new")))
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals("new", viewModel.state.value.debts.single().publicId)

        // Release the now-stale refresh; its empty snapshot must NOT revert the just-created list.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals("new", viewModel.state.value.debts.single().publicId)
    }

    @Test
    fun staleRefreshDoesNotClobberReloadedLedger() = runTest(dispatcher) {
        // Ledger switch: a slow prior refresh must not show the old ledger's debts under the new one.
        val repo = FakeDebtActions(listResult = Result.success(listOf(sampleDebt("ledgerA"))))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        // A slow refresh stalls (it captured ledger A's debts)...
        val gate = CompletableDeferred<Unit>()
        repo.listGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then a ledger switch reloads with ledger B's debts.
        repo.listGate = null
        repo.listResult = Result.success(listOf(sampleDebt("ledgerB")))
        viewModel.reload()
        advanceUntilIdle()
        assertEquals("ledgerB", viewModel.state.value.debts.single().publicId)

        // Release the stale refresh; ledger A's debts must NOT leak back under ledger B.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals("ledgerB", viewModel.state.value.debts.single().publicId)
        assertEquals(false, viewModel.state.value.isLoading)
    }
}

private class FakeDebtActions(
    private val canModify: Boolean = true,
    var listResult: Result<List<Debt>> = Result.success(emptyList()),
    var createResult: Result<Debt> = Result.success(sampleDebt()),
    var parseBillResult: Result<DebtBillSuggestion> = Result.success(blankBillSuggestion()),
) : DebtActions {
    val createDrafts = mutableListOf<DebtDraft>()
    val parseBillCalls = mutableListOf<String>()
    var listCalls = 0

    /** When set, listDebts() stalls until completed — used to interleave a slow load. */
    var listGate: CompletableDeferred<Unit>? = null

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun listDebts(): Result<List<Debt>> {
        listCalls++
        // Capture the result at entry so a stalled load returns the snapshot it started with, even
        // if a newer load swaps listResult in the meantime.
        val captured = listResult
        listGate?.await()
        return captured
    }

    override suspend fun getDebt(publicId: String): Result<Debt> = Result.success(sampleDebt(publicId))

    override suspend fun createDebt(draft: DebtDraft): Result<Debt> {
        createDrafts += draft
        return createResult
    }

    override suspend fun parseDebtBillImage(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
    ): Result<DebtBillSuggestion> {
        parseBillCalls += fileName
        return parseBillResult
    }

    override suspend fun recordRepayment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
    ): Result<Debt> = Result.success(sampleDebt(publicId))

    override suspend fun recordAdjustment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
        reason: String,
    ): Result<Debt> = Result.success(sampleDebt(publicId))

    override suspend fun voidDebt(
        publicId: String,
        expectedRowVersion: Long,
        reason: String,
    ): Result<Debt> = Result.success(sampleDebt(publicId))

    override suspend fun setDebtKind(
        publicId: String,
        expectedRowVersion: Long,
        debtKind: String,
    ): Result<Debt> = Result.success(sampleDebt(publicId))
}

private fun blankBillSuggestion(): DebtBillSuggestion = DebtBillSuggestion(
    merchant = null,
    principalAmountCents = null,
    installmentCount = null,
    installmentPeriodMonths = null,
    perPeriodAmountCents = null,
    repaymentDay = null,
    sourceText = "",
    confidence = null,
)

private fun sampleDebt(publicId: String = "debt-1"): Debt = Debt(
    publicId = publicId,
    ledgerId = "owner",
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyAccountId = null,
    counterpartyLabel = "房东",
    principalAmountCents = 50_000,
    remainingAmountCents = 50_000,
    paidAmountCents = 0,
    status = DebtLinkStatuses.OPEN,
    sourceType = DebtSourceTypes.MANUAL,
    sourceId = null,
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-15T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = 1,
)
