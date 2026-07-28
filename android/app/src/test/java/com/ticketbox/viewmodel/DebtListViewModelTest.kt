package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
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

    @Test
    fun untouchedDraftBackfillsLedgerHomeCurrencyWhenLoadLands() = runTest(dispatcher) {
        // PR#255 P1-2/P1-3：add sheet 在初始列表请求未回时已按 CNY 兜底开好草稿；响应
        // 到达后未触碰的草稿必须回填账本真实 home 币种（JPY 账本下输 1200 → 1200 minor，
        // 不 ×100）；回填前 homeCurrencyResolved=false，创建被禁用。
        val gate = CompletableDeferred<Unit>()
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"))),
            createResult = Result.success(sampleDebt("created")),
        )
        repo.listGate = gate
        val viewModel = DebtListViewModel(repo)
        runCurrent()
        // 加载未回：草稿仍是兜底币种，币种未确认。
        assertEquals(CurrencyCode.CNY, viewModel.state.value.addDraft.homeCurrency)
        assertEquals(false, viewModel.state.value.homeCurrencyResolved)

        gate.complete(Unit)
        advanceUntilIdle()

        assertEquals(CurrencyCode.JPY, viewModel.state.value.addDraft.homeCurrency)
        assertEquals(true, viewModel.state.value.homeCurrencyResolved)
        // 列表回来后输入的金额按 JPY 解析（整数即 minor，不 ×100）。
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1_200L, repo.createDrafts.single().principalAmountCents)
    }

    @Test
    fun touchedDraftRebindsCurrencyAndRevalidatesWhenLoadLands() = runTest(dispatcher) {
        // PR#255 P1-3：用户已输入内容的草稿也随响应重绑到权威币种（旧行为让 stale CNY
        // 存活，提交会放大 100×）；文本保留，若金额在新币种下解析不出则立即亮校验错误。
        val gate = CompletableDeferred<Unit>()
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"))),
        )
        repo.listGate = gate
        val viewModel = DebtListViewModel(repo)
        runCurrent()

        // 加载未回时用户已按兜底口径输入（"12.00" 在 CNY 是 1200 分，在 JPY 非法）。
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("12.00")
        gate.complete(Unit)
        advanceUntilIdle()

        val draft = viewModel.state.value.addDraft
        assertEquals(CurrencyCode.JPY, draft.homeCurrency)
        assertEquals("12.00", draft.amountYuanInput)
        assertTrue(draft.userTouched)
        assertTrue(draft.validationError != null)
        // 提前重校验后：金额在新币种下不合法，提交仍被拦，createDebt 不可达。
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.createDrafts.isEmpty())
    }

    @Test
    fun touchedDraftRebindKeepsValidAmountSilently() = runTest(dispatcher) {
        // P1-3 同伴路径：已输金额在新币种下仍合法时静默重绑，不亮错误、可正常提交。
        val gate = CompletableDeferred<Unit>()
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"))),
            createResult = Result.success(sampleDebt("created")),
        )
        repo.listGate = gate
        val viewModel = DebtListViewModel(repo)
        runCurrent()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        gate.complete(Unit)
        advanceUntilIdle()

        val draft = viewModel.state.value.addDraft
        assertEquals(CurrencyCode.JPY, draft.homeCurrency)
        assertNull(draft.validationError)
        viewModel.submitDraft()
        advanceUntilIdle()
        // JPY 整数解析：1200 minor，不是 CNY 口径的 120000。
        assertEquals(1_200L, repo.createDrafts.single().principalAmountCents)
    }

    @Test
    fun submitDraftBeforeHomeCurrencyResolvedDoesNotCreate() = runTest(dispatcher) {
        // PR#255 P1-3 回归：列表请求在途（币种未确认）时提交被 VM 防线拦下 —— 不得按
        // CNY 兜底口径把 "1200" 放大成 120000 送到 JPY 账本；响应落地重绑后才可提交。
        val gate = CompletableDeferred<Unit>()
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"))),
            createResult = Result.success(sampleDebt("created")),
        )
        repo.listGate = gate
        val viewModel = DebtListViewModel(repo)
        runCurrent()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.createDrafts.isEmpty())

        gate.complete(Unit)
        advanceUntilIdle()
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1_200L, repo.createDrafts.single().principalAmountCents)
    }

    @Test
    fun refreshFailureKeepsCreationDisabled() = runTest(dispatcher) {
        // P1-3：加载失败时币种仍未知，创建保持禁用（不回落 CNY 口径提交），重试成功才放开。
        val repo = FakeDebtActions(listResult = Result.failure(RuntimeException("offline")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()
        assertEquals(false, viewModel.state.value.homeCurrencyResolved)

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.createDrafts.isEmpty())

        repo.listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY")))
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals(true, viewModel.state.value.homeCurrencyResolved)
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1_200L, repo.createDrafts.single().principalAmountCents)
    }

    @Test
    fun emptyLedgerLoadKeepsCreationBlockedUntilFirstRecord() = runTest(dispatcher) {
        // PR#255 R4 P1：空账本（如新建 JPY/KRW 账本）没有任何 record 级权威币种 ——
        // 列表请求成功但 items 为空时，不得按 CNY 兜底声明币种已确认并放开提交：旧逻辑
        // 会把 "1200" 以 120000 minor units 提交，后端解释为 ¥120,000/₩120,000（100×
        // 资损，ADR-0061 C03 禁默认-CNY 猜测）。保持阻断直到首条记录带来权威币种。
        val repo = FakeDebtActions(listResult = Result.success(emptyList()))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.debts.isEmpty())
        assertEquals(false, viewModel.state.value.homeCurrencyResolved)
        assertEquals(CurrencyCode.CNY, viewModel.state.value.addDraft.homeCurrency)

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.createDrafts.isEmpty())

        // 首条记录落地带来 record 级权威币种后放开：草稿重绑 JPY，按零小数口径提交。
        repo.listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY")))
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals(true, viewModel.state.value.homeCurrencyResolved)
        assertEquals(CurrencyCode.JPY, viewModel.state.value.addDraft.homeCurrency)
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1_200L, repo.createDrafts.single().principalAmountCents)
    }

    @Test
    fun loadedDebtsCarryRecordHomeCurrencyForRowLens() = runTest(dispatcher) {
        // PR#255 R5 P2：ExternalDebtRow 的金额渲染走 CurrencyDisplay.forRecord(
        // debt.homeCurrencyCode) —— 钉死 VM 数据通路：列表加载后每条 Debt 的 record 级
        // homeCurrencyCode 原样留在 state（不被恒 Base 的环境 display 覆盖）。
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"))),
        )
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals("JPY", viewModel.state.value.debts.single().homeCurrencyCode)
    }

    @Test
    fun reloadClearsStaleLedgerDraftAndBlocksSubmitUntilResolved() = runTest(dispatcher) {
        // PR#255 R5 P2 + 测试钉：JPY 账本已输 "1200" 的草稿切账本时不得随 rebind 静默
        // 重解释（落 CNY 账本即 120000 minor，100×）—— reload() 同步清掉草稿；新账本
        // 响应未回期间 homeCurrencyResolved=false，submitDraft 被拒（旧草稿永不可达
        // 创建路径）。
        val gate = CompletableDeferred<Unit>()
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"))),
            createResult = Result.success(sampleDebt("created")),
        )
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()
        assertEquals(true, viewModel.state.value.homeCurrencyResolved)

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")

        // 账本切换：reload 的拉取 stall 在 listDebts（响应未回）。
        repo.listResult = Result.success(listOf(sampleDebt("cny-debt").copy(homeCurrencyCode = "CNY")))
        repo.listGate = gate
        viewModel.reload()
        runCurrent()

        // 草稿已同步清空、币种回到未确认，提交被 VM 防线拦下。
        val cleared = viewModel.state.value.addDraft
        assertEquals("", cleared.counterpartyLabel)
        assertEquals("", cleared.amountYuanInput)
        assertEquals(false, cleared.userTouched)
        assertEquals(CurrencyCode.CNY, cleared.homeCurrency) // 重绑前只剩兜底口径
        assertEquals(false, viewModel.state.value.homeCurrencyResolved)
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.createDrafts.isEmpty())

        // 新账本响应落地：创建重新放开，全新草稿重绑到新账本权威币种。
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(true, viewModel.state.value.homeCurrencyResolved)
        assertEquals(CurrencyCode.CNY, viewModel.state.value.addDraft.homeCurrency)
    }

    @Test
    fun markBillParsePreparingRejectedUntilHomeCurrencyResolved() = runTest(dispatcher) {
        // PR#255 R5 P3：解析入口与 submitDraft 同一道 homeCurrencyResolved 门 —— 币种
        // 未确认时预填必按兜底口径格式化、重绑后静默变义，故空账本期间入口拒绝开启；
        // 首条记录带来 record 级权威币种后放行。
        val repo = FakeDebtActions(listResult = Result.success(emptyList()))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals(false, viewModel.state.value.homeCurrencyResolved)
        assertEquals(false, viewModel.markBillParsePreparing())
        assertEquals(false, viewModel.state.value.isParsingBill)

        repo.listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY")))
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals(true, viewModel.markBillParsePreparing())
        assertEquals(true, viewModel.state.value.isParsingBill)
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
