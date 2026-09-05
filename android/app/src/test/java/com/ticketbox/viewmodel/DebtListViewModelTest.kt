package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.domain.model.CurrencyCode
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
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt())),
            createResult = Result.success(sampleDebt("created")),
        )
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
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt())),
            createResult = Result.success(sampleDebt("created")),
        )
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
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt())),
            createResult = Result.success(sampleDebt("created")),
        )
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
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt())),
            createResult = Result.success(sampleDebt("created")),
        )
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
            // R5 P3 起解析入口与 submitDraft 同门：账本币种须先 resolved（非空列表）才放行。
            listResult = Result.success(listOf(sampleDebt())),
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
        // 预填走币种感知族 formatMinorAmountInput：2 位小数 home 固定两位小数（120000 → "1200.00"，
        // 与 formatAmountInput 全家口径一致；旧本地 helper 的「整元去尾零」写法已删）。
        assertEquals("1200.00", draft.amountYuanInput)
        assertEquals(DebtKinds.INSTALLMENT, draft.kind)
        assertEquals("12", draft.installmentCountInput)
        assertEquals("1", draft.installmentPeriodInput)
        assertEquals(false, viewModel.state.value.isParsingBill)
        assertTrue(viewModel.state.value.pendingBillParsePrefill)
        viewModel.ackBillParsePrefill()
        assertEquals(false, viewModel.state.value.pendingBillParsePrefill)
    }

    @Test
    fun parseDebtBillSkipsAmountPrefillOnNonCnyLedger() = runTest(dispatcher) {
        // PR#255 R8-2：provider 声明金额单位为 CNY 分（两位小数）。JPY/KRW 零小数账本接受
        // 建议时，预填会把 120000 分当账本 minor 提交（100×）→ 金额字段不预填、留用户
        // 手填；其它字段（平台/期数/周期）保留预填。CNY 账本路径见上钉。
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"))),
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
        assertEquals("花呗", draft.counterpartyLabel)
        assertEquals("", draft.amountYuanInput) // 金额不预填（分单位与账本 minor 不同源）
        assertEquals(DebtKinds.INSTALLMENT, draft.kind)
        assertEquals("12", draft.installmentCountInput)
        assertEquals(CurrencyCode.JPY, draft.homeCurrency)
        assertTrue(viewModel.state.value.pendingBillParsePrefill)
    }

    @Test
    fun submitDraftWithBlankCounterpartyShowsValidationWithoutCreate() = runTest(dispatcher) {
        val repo = FakeDebtActions(listResult = Result.success(listOf(sampleDebt())))
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
        val repo = FakeDebtActions(listResult = Result.success(listOf(sampleDebt())))
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
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt())),
            createResult = Result.failure(RuntimeException("boom")),
        )
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.updateDraftNote("出差垫付车费")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.addDraft.validationError != null)
        // The form retains the user's input so they can retry, not wiped.
        assertEquals("小王", viewModel.state.value.addDraft.counterpartyLabel)
        assertEquals("出差垫付车费", viewModel.state.value.addDraft.note)
        assertEquals("出差垫付车费", repo.createDrafts.single().note)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun submitDraftSuccessSetsAddSucceededThenResetClears() = runTest(dispatcher) {
        // The one-shot success signal is what drives the sheet to close — set ONLY on a real
        // create success, then cleared by resetDraft when the screen closes (mirrors the
        // LedgerViewModel.manualCreateDone ack convention).
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt())),
            createResult = Result.success(sampleDebt("created")),
        )
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
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt())),
            createResult = Result.failure(RuntimeException("boom")),
        )
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
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt())),
            createResult = Result.success(sampleDebt("created")),
        )
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
        // （R4 P1 起空账本创建被币种 gate 阻断，故场景从既有 1 条记录的账本起步。）
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("old"))),
            createResult = Result.success(sampleDebt("new")),
        )
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle() // init refresh → debts = [old]

        // A slow refresh stalls inside listDebts() (it captured the pre-create snapshot)...
        val gate = CompletableDeferred<Unit>()
        repo.listGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then the user creates a debt; submitDraft's success refresh delivers the new list.
        repo.listGate = null
        repo.listResult = Result.success(listOf(sampleDebt("old"), sampleDebt("new")))
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(listOf("old", "new"), viewModel.state.value.debts.map { it.publicId })

        // Release the now-stale refresh; its pre-create snapshot must NOT revert the just-created list.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(listOf("old", "new"), viewModel.state.value.debts.map { it.publicId })
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
