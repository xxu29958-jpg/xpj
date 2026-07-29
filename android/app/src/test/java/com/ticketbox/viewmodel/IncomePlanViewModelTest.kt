package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import java.lang.reflect.Proxy
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class IncomePlanViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun initRefreshLoadsActiveAndArchivedAndTotal() = runTest(dispatcher) {
        val repo = FakeRepository(
            active = IncomePlanListing(
                plans = listOf(plan("p1", 100_000, status = IncomePlanStatus.ACTIVE)),
                totalActiveAmountCents = 100_000,
            ),
            archived = listOf(plan("p2", 50_000, status = IncomePlanStatus.ARCHIVED)),
        )
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        val state = viewModel.state.value
        assertFalse(state.isLoading)
        assertEquals(1, state.activePlans.size)
        assertEquals(1, state.archivedPlans.size)
        assertEquals(100_000L, state.totalActiveAmountCents)
    }

    @Test
    fun stableAuthorityRoundTripClearsDraftAndReloadsTheExistingViewModel() = runTest(dispatcher) {
        val repo = FakeRepository(
            active = IncomePlanListing(listOf(plan("owner-a", 100_000)), 100_000),
        )
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.updateDraftLabel("owner draft")

        repo.active = IncomePlanListing(listOf(plan("family", 200_000)), 200_000)
        repo.activeAccessFlow.value = incomePlanAccess(ownerKey = "owner-b")
        advanceUntilIdle()

        assertEquals(listOf("family"), viewModel.state.value.activePlans.map(IncomePlan::publicId))
        assertEquals("", viewModel.state.value.addDraft.label)

        repo.active = IncomePlanListing(listOf(plan("owner-b", 300_000)), 300_000)
        repo.activeAccessFlow.value = incomePlanAccess(ownerKey = "owner-a-restored")
        advanceUntilIdle()

        assertEquals(listOf("owner-b"), viewModel.state.value.activePlans.map(IncomePlan::publicId))
        assertEquals(3, repo.listActiveCalls)
    }

    @Test
    fun stalePreviousLedgerRefreshCannotOverwriteCurrentLedger() = runTest(dispatcher) {
        val staleOwnerResult = CompletableDeferred<Result<IncomePlanListing>>()
        val familyListing = IncomePlanListing(listOf(plan("family", 200_000)), 200_000)
        val repo = FakeRepository(active = familyListing)
        repo.activeResponder = { call ->
            if (call == 1) staleOwnerResult.await() else Result.success(familyListing)
        }
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()

        repo.activeAccessFlow.value = incomePlanAccess(ledgerId = "family", ownerKey = "family-owner")
        advanceUntilIdle()
        assertEquals(listOf("family"), viewModel.state.value.activePlans.map(IncomePlan::publicId))

        staleOwnerResult.complete(
            Result.success(IncomePlanListing(listOf(plan("owner", 100_000)), 100_000)),
        )
        advanceUntilIdle()

        assertEquals(listOf("family"), viewModel.state.value.activePlans.map(IncomePlan::publicId))
    }

    @Test
    fun staleSameBindingRefreshCannotOverwriteLatestResult() = runTest(dispatcher) {
        val stale = CompletableDeferred<Result<IncomePlanListing>>()
        val latest = CompletableDeferred<Result<IncomePlanListing>>()
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        var refreshCall = 0
        repo.activeResponder = {
            if (++refreshCall == 1) stale.await() else latest.await()
        }

        viewModel.refresh()
        advanceUntilIdle()
        viewModel.refresh()
        advanceUntilIdle()
        latest.complete(
            Result.success(IncomePlanListing(listOf(plan("latest", 200_000)), 200_000)),
        )
        advanceUntilIdle()
        stale.complete(
            Result.success(IncomePlanListing(listOf(plan("stale", 100_000)), 100_000)),
        )
        advanceUntilIdle()

        assertEquals(listOf("latest"), viewModel.state.value.activePlans.map(IncomePlan::publicId))
    }

    @Test
    fun previousLedgerMutationCompletionCannotRefreshCurrentLedger() = runTest(dispatcher) {
        val archiveResult = CompletableDeferred<Result<IncomePlan>>()
        val repo = FakeRepository()
        repo.archiveResponder = { archiveResult.await() }
        var dataChangedCalls = 0
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions()) { dataChangedCalls += 1 }
        advanceUntilIdle()

        viewModel.archive("owner-plan", 1L)
        advanceUntilIdle()
        repo.activeAccessFlow.value = incomePlanAccess(ledgerId = "family", ownerKey = "family-owner")
        advanceUntilIdle()

        archiveResult.complete(
            Result.success(plan("owner-plan", 100, status = IncomePlanStatus.ARCHIVED)),
        )
        advanceUntilIdle()

        assertNull(viewModel.state.value.flashMessage)
        assertEquals(0, dataChangedCalls)
        assertEquals(2, repo.listActiveCalls)
    }

    @Test
    fun submitDraftValidatesBeforeNetworkCall() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.updateDraftLabel("")
        viewModel.updateDraftAmount("abc")
        viewModel.updateDraftPayDay("99")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(0, repo.createCalls)
        assertNotNull(viewModel.state.value.addDraft.validationError)
    }

    @Test
    fun submitDraftHappyPathClearsAndRefreshes() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.updateDraftLabel("工资")
        viewModel.updateDraftSource(IncomeSourceType.SALARY)
        viewModel.updateDraftAmount("10000")
        viewModel.updateDraftPayDay("10")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1, repo.createCalls)
        assertEquals(IncomeSourceType.SALARY, repo.lastDraft?.sourceType)
        assertEquals(IncomeFrequency.ONE_TIME, repo.lastDraft?.frequency)
        assertNotNull(repo.lastDraft?.incomeMonth)
        assertEquals(1_000_000L, repo.lastDraft?.amountCents)
        assertEquals(10, repo.lastDraft?.payDay)
        assertEquals(UiText.res(R.string.income_plan_added), viewModel.state.value.flashMessage)
        assertEquals("", viewModel.state.value.addDraft.label) // reset
    }

    @Test
    fun submitOneTimeDraftSendsIncomeMonth() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.updateDraftLabel("项目尾款")
        viewModel.updateDraftSource(IncomeSourceType.FREELANCE)
        viewModel.updateDraftFrequency(IncomeFrequency.ONE_TIME)
        viewModel.updateDraftIncomeMonth("2026-06")
        viewModel.updateDraftAmount("2500")
        viewModel.updateDraftPayDay("28")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertEquals(1, repo.createCalls)
        assertEquals(IncomeFrequency.ONE_TIME, repo.lastDraft?.frequency)
        assertEquals("2026-06", repo.lastDraft?.incomeMonth)
        assertEquals(250_000L, repo.lastDraft?.amountCents)
    }

    @Test
    fun submitDraftParsesAmountInLedgerCapability() = runTest(dispatcher) {
        // PR#255 R12-D：解析口径取列表信封 capability（R6 同源）—— JPY 账本 "1200" →
        // 1200 minor（零小数不 ×100），不再落 CNY 兜底放大 100×。
        val debts = CapabilityDebtActions(
            page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY"),
        )
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, debts)
        advanceUntilIdle()

        viewModel.updateDraftLabel("工资")
        viewModel.updateDraftAmount("1200")
        viewModel.updateDraftPayDay("10")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertEquals(1, repo.createCalls)
        assertEquals(1_200L, repo.lastDraft?.amountCents)
    }

    @Test
    fun submitDraftBlockedWhenCapabilityUnsupported() = runTest(dispatcher) {
        // R12-D：capability 在支持集外（新版服务端币种）→ 草稿 homeCurrency=null → 禁写 +
        // 明示文案，create 不可达。
        val debts = CapabilityDebtActions(
            page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "VND"),
        )
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, debts)
        advanceUntilIdle()

        assertNull(viewModel.state.value.addDraft.homeCurrency)
        viewModel.updateDraftLabel("工资")
        viewModel.updateDraftAmount("1200")
        viewModel.updateDraftPayDay("10")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertEquals(0, repo.createCalls)
        assertEquals(
            UiText.res(R.string.currency_unconfirmed_write_blocked),
            viewModel.state.value.addDraft.validationError,
        )
    }

    @Test
    fun updateDraftAmountReportsParseFailureImmediately() = runTest(dispatcher) {
        // PR#255 R14-2：JPY 账本输 "12.50" 即时报解析失败（不再静默 isValid=false）；改合法即清。
        val debts = CapabilityDebtActions(
            page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY"),
        )
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, debts)
        advanceUntilIdle()

        viewModel.updateDraftAmount("12.50")
        assertEquals(
            UiText.res(R.string.expense_edit_amount_invalid),
            viewModel.state.value.addDraft.validationError,
        )

        viewModel.updateDraftAmount("1250")
        assertNull(viewModel.state.value.addDraft.validationError)
    }

    @Test
    fun shiftDraftIncomeMonthKeepsInternalWireValue() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.updateDraftIncomeMonth("2026-06")

        viewModel.shiftDraftIncomeMonth(-1L)
        assertEquals("2026-05", viewModel.state.value.addDraft.incomeMonthInput)

        viewModel.shiftDraftIncomeMonth(2L)
        assertEquals("2026-07", viewModel.state.value.addDraft.incomeMonthInput)
    }

    @Test
    fun submitDraftSurfacesRepositoryError() = runTest(dispatcher) {
        val repo = FakeRepository(createResult = Result.failure(RuntimeException("网络异常")))
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.updateDraftLabel("x")
        viewModel.updateDraftAmount("100")
        viewModel.updateDraftPayDay("1")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(UiText.raw("网络异常"), viewModel.state.value.addDraft.validationError)
        assertFalse(viewModel.state.value.isSubmitting)
    }

    @Test
    fun submitDraftSuccessSetsAddSucceededThenResetClears() = runTest(dispatcher) {
        // The one-shot success signal is what drives the add sheet to close — set ONLY on a real
        // create success, then cleared by resetDraft when the screen closes (mirrors the
        // LedgerViewModel.manualCreateDone ack convention).
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.updateDraftLabel("工资")
        viewModel.updateDraftAmount("10000")
        viewModel.updateDraftPayDay("10")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.addSucceeded)
        viewModel.resetDraft()
        assertFalse(viewModel.state.value.addSucceeded)
    }

    @Test
    fun submitDraftFailureLeavesAddSucceededFalse() = runTest(dispatcher) {
        // A backend failure must NOT signal the screen to close — the sheet stays open with its
        // validationError instead of vanishing while the user believes the plan was created.
        val repo = FakeRepository(createResult = Result.failure(RuntimeException("网络异常")))
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.updateDraftLabel("x")
        viewModel.updateDraftAmount("100")
        viewModel.updateDraftPayDay("1")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertFalse(viewModel.state.value.addSucceeded)
    }

    @Test
    fun archiveTriggersRepositoryAndFlashMessage() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.archive("some-id", 1L)
        advanceUntilIdle()
        assertEquals("some-id", repo.lastArchiveId)
        assertEquals(UiText.res(R.string.income_plan_archived), viewModel.state.value.flashMessage)
    }

    @Test
    fun restoreTriggersRepositoryAndFlashMessage() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.restore("some-id", 1L)
        advanceUntilIdle()
        assertEquals("some-id", repo.lastRestoreId)
        assertEquals(UiText.res(R.string.income_plan_restored), viewModel.state.value.flashMessage)
    }

    @Test
    fun dismissFlashClearsMessage() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.archive("x", 1L)
        advanceUntilIdle()
        viewModel.dismissFlash()
        assertNull(viewModel.state.value.flashMessage)
    }

    @Test
    fun viewerRoleBlocksWriteAttempts() = runTest(dispatcher) {
        val repo = FakeRepository(canModify = false)
        val viewModel = IncomePlanViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        assertFalse(viewModel.state.value.canModify)
    }

    @Test
    fun draftAmountParsing() {
        // R12-D 起解析币种由草稿持有（信封 capability 注入）；裸构造须显式给币种。
        val draft = IncomePlanDraftUi(amountYuanInput = "123.45", homeCurrency = CurrencyCode.CNY)
        assertEquals(12345L, draft.parsedAmountCents())
        // §3 BigDecimal 精度：>2 位小数 HALF_UP 精确进位。"1.005" → 101；旧 Double Math.round 给 100
        // （1.005*100 的 double 是 100.4999… → 100），故此断言会在退回 Double 时变红。
        assertEquals(101L, IncomePlanDraftUi(amountYuanInput = "1.005", homeCurrency = CurrencyCode.CNY).parsedAmountCents())
        // 收入计划允许 0（与 DebtList 的 > 0 不同：这里是 >= 0 边界）。
        assertEquals(0L, IncomePlanDraftUi(amountYuanInput = "0", homeCurrency = CurrencyCode.CNY).parsedAmountCents())
        // 拒负：极小负额在分空间 HALF_UP 舍入到 0，也按元符号拒，不静默当成 0 元计划。
        assertEquals(null, IncomePlanDraftUi(amountYuanInput = "-0.004", homeCurrency = CurrencyCode.CNY).parsedAmountCents())
        // 溢出 Long 安全返回 null（旧 Double Math.round 会回 Long.MAX 垃圾值）。
        assertEquals(null, IncomePlanDraftUi(amountYuanInput = "99999999999999999999", homeCurrency = CurrencyCode.CNY).parsedAmountCents())
        assertEquals(null, IncomePlanDraftUi(amountYuanInput = "abc", homeCurrency = CurrencyCode.CNY).parsedAmountCents())
        assertEquals(null, IncomePlanDraftUi(amountYuanInput = "-5").parsedAmountCents())
        assertEquals(null, IncomePlanDraftUi(amountYuanInput = "").parsedAmountCents())
    }

    @Test
    fun draftPayDayParsing() {
        assertEquals(15, IncomePlanDraftUi(payDayInput = "15").parsedPayDay())
        assertEquals(null, IncomePlanDraftUi(payDayInput = "32").parsedPayDay())
        assertEquals(null, IncomePlanDraftUi(payDayInput = "0").parsedPayDay())
        assertEquals(null, IncomePlanDraftUi(payDayInput = "abc").parsedPayDay())
    }

    @Test
    fun draftIncomeMonthParsing() {
        assertEquals("2026-06", IncomePlanDraftUi(incomeMonthInput = "2026-06").parsedIncomeMonth())
        assertEquals(null, IncomePlanDraftUi(incomeMonthInput = "2026-13").parsedIncomeMonth())
        assertEquals(null, IncomePlanDraftUi(incomeMonthInput = "2026/06").parsedIncomeMonth())
    }

    @Test
    fun draftIsValidRequiresAllThree() {
        assertTrue(
            IncomePlanDraftUi(label = "x", amountYuanInput = "100", payDayInput = "1", homeCurrency = CurrencyCode.CNY).isValid,
        )
        assertTrue(
            IncomePlanDraftUi(
                label = "x",
                frequency = IncomeFrequency.ONE_TIME,
                incomeMonthInput = "2026-06",
                amountYuanInput = "100",
                payDayInput = "1",
                homeCurrency = CurrencyCode.CNY,
            ).isValid,
        )
        assertFalse(
            IncomePlanDraftUi(
                label = "x",
                frequency = IncomeFrequency.ONE_TIME,
                incomeMonthInput = "2026-13",
                amountYuanInput = "100",
                payDayInput = "1",
            ).isValid,
        )
        assertFalse(IncomePlanDraftUi(amountYuanInput = "100", payDayInput = "1").isValid)
        assertFalse(IncomePlanDraftUi(label = "x", payDayInput = "1").isValid)
        assertFalse(
            IncomePlanDraftUi(label = "x", amountYuanInput = "100", payDayInput = "99").isValid,
        )
    }

    private fun plan(
        id: String,
        amountCents: Long,
        status: IncomePlanStatus = IncomePlanStatus.ACTIVE,
    ) = IncomePlan(
        publicId = id,
        label = "label-$id",
        sourceType = IncomeSourceType.SALARY,
        frequency = IncomeFrequency.MONTHLY,
        incomeMonth = null,
        amountCents = amountCents,
        payDay = 1,
        status = status,
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-01T00:00:00Z",
        rowVersion = 1L,
        archivedAt = if (status == IncomePlanStatus.ARCHIVED) "2026-05-15T00:00:00Z" else null,
    )

    private class FakeRepository(
        var active: IncomePlanListing = IncomePlanListing(emptyList(), 0L),
        private val archived: List<IncomePlan> = emptyList(),
        private val canModify: Boolean = true,
        private val createResult: Result<IncomePlan>? = null,
    ) : IncomePlanActions {
        val activeAccessFlow = MutableStateFlow<LedgerAccessContext?>(
            incomePlanAccess(canModify = canModify),
        )
        var createCalls = 0
        var listActiveCalls = 0
        var lastDraft: IncomePlanDraft? = null
        var lastArchiveId: String? = null
        var lastRestoreId: String? = null
        var activeResponder: (suspend (Int) -> Result<IncomePlanListing>)? = null
        var archiveResponder: (suspend () -> Result<IncomePlan>)? = null

        override fun canModifyLedger(): Boolean = canModify

        override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> = activeAccessFlow

        override suspend fun listActive(
            expectedBinding: LogicalSessionBinding,
        ): Result<IncomePlanListing> {
            listActiveCalls += 1
            return activeResponder?.invoke(listActiveCalls) ?: Result.success(active)
        }

        override suspend fun listIncluding(
            expectedBinding: LogicalSessionBinding,
            status: IncomePlanStatus,
        ): Result<List<IncomePlan>> =
            Result.success(archived)

        override suspend fun create(
            expectedBinding: LogicalSessionBinding,
            draft: IncomePlanDraft,
        ): Result<IncomePlan> {
            createCalls += 1
            lastDraft = draft
            return createResult ?: Result.success(stub(draft.label))
        }

        override suspend fun update(publicId: String, patch: com.ticketbox.data.repository.IncomePlanPatch) =
            Result.success(stub(publicId))

        override suspend fun archive(
            expectedBinding: LogicalSessionBinding,
            publicId: String,
            expectedRowVersion: Long,
        ): Result<IncomePlan> {
            lastArchiveId = publicId
            return archiveResponder?.invoke()
                ?: Result.success(stub(publicId, IncomePlanStatus.ARCHIVED))
        }

        override suspend fun restore(
            expectedBinding: LogicalSessionBinding,
            publicId: String,
            expectedRowVersion: Long,
        ): Result<IncomePlan> {
            lastRestoreId = publicId
            return Result.success(stub(publicId, IncomePlanStatus.ACTIVE))
        }

        private fun stub(id: String, status: IncomePlanStatus = IncomePlanStatus.ACTIVE) = IncomePlan(
            publicId = id,
            label = id,
            sourceType = IncomeSourceType.SALARY,
            frequency = IncomeFrequency.MONTHLY,
            incomeMonth = null,
            amountCents = 100,
            payDay = 1,
            status = status,
            createdAt = "2026-05-01T00:00:00Z",
            updatedAt = "2026-05-01T00:00:00Z",
            rowVersion = 1L,
            archivedAt = if (status == IncomePlanStatus.ARCHIVED) "2026-05-15T00:00:00Z" else null,
        )
    }
}

private fun incomePlanBinding(
    ledgerId: String = "owner",
    ownerKey: String = "owner",
): LogicalSessionBinding = LogicalSessionBinding(
    serverUrl = "https://api.example.com",
    ledgerId = ledgerId,
    ownerKey = ownerKey,
    sessionGeneration = "session-$ownerKey",
    bindingRevision = "binding-$ownerKey-$ledgerId",
)

private fun incomePlanAccess(
    ledgerId: String = "owner",
    ownerKey: String = "owner",
    canModify: Boolean = true,
): LedgerAccessContext = LedgerAccessContext(
    binding = incomePlanBinding(ledgerId, ownerKey),
    canModify = canModify,
)

/**
 * #258-R2 项1：IncomePlanViewModel 币种解析代际守卫钉（同文件新类，镜像
 * LedgerViewModelCurrencyRelatchTest 范式 —— 主类已贴 detekt 门类门）。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class IncomePlanViewModelCurrencyRelatchTest {
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
    fun staleCurrencyResolutionDoesNotOverwriteNewerResult() = runTest(dispatcher) {
        // R2-1：init 解析挂起中 resetDraft 触发第二次解析 —— 新结果（JPY）先落定后，
        // 旧结果（CNY）不得覆写（last-writer-wins）。
        val debts = DeferredIncomeDebtActions()
        val viewModel = IncomePlanViewModel(RelatchIncomeActions(), debts)
        advanceUntilIdle()

        viewModel.resetDraft()
        runCurrent()
        assertEquals(2, debts.calls.size)

        debts.calls[1].complete(
            Result.success(DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY")),
        )
        advanceUntilIdle()
        assertEquals(CurrencyCode.JPY, viewModel.state.value.ledgerCurrency)

        debts.calls[0].complete(
            Result.success(DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "CNY")),
        )
        advanceUntilIdle()
        assertEquals(CurrencyCode.JPY, viewModel.state.value.ledgerCurrency)
    }

    @Test
    fun failedResolutionKeepsPreviouslyResolvedCurrency() = runTest(dispatcher) {
        // #258-R3 项1：解析失败不覆写上次已确认值 —— JPY 解析成功后 resetDraft 触发
        // 的重解析失败，ledgerCurrency 保持 JPY（卡面不打回 ¥12.00）。
        val debts = DeferredIncomeDebtActions()
        val viewModel = IncomePlanViewModel(RelatchIncomeActions(), debts)
        advanceUntilIdle()

        debts.calls[0].complete(
            Result.success(DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY")),
        )
        advanceUntilIdle()
        assertEquals(CurrencyCode.JPY, viewModel.state.value.ledgerCurrency)

        viewModel.resetDraft()
        runCurrent()
        debts.calls[1].complete(Result.failure(IllegalStateException("offline")))
        advanceUntilIdle()
        assertEquals(CurrencyCode.JPY, viewModel.state.value.ledgerCurrency)
    }
}

/** 项1 钉的最小 IncomePlanActions（嵌套 FakeRepository 为类内私有不可复用）。 */
private class RelatchIncomeActions : IncomePlanActions by unsupportedIncomeActions() {
    override fun canModifyLedger(): Boolean = true

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> =
        MutableStateFlow(incomePlanAccess())

    override suspend fun listActive(expectedBinding: LogicalSessionBinding): Result<IncomePlanListing> =
        Result.success(IncomePlanListing(emptyList(), 0L))

    override suspend fun listIncluding(
        expectedBinding: LogicalSessionBinding,
        status: IncomePlanStatus,
    ): Result<List<IncomePlan>> = Result.success(emptyList())
}

/** 逐调用挂起闸门的账本币种 fake（项1 代际乱序钉）。 */
private class DeferredIncomeDebtActions : DebtActions by unsupportedIncomeDebtActions() {
    val calls = mutableListOf<CompletableDeferred<Result<DebtListPage>>>()

    override fun canModifyLedger(): Boolean = true

    override suspend fun listDebts(): Result<DebtListPage> {
        val gate = CompletableDeferred<Result<DebtListPage>>()
        calls += gate
        return gate.await()
    }
}

@Suppress("UNCHECKED_CAST")
private fun unsupportedIncomeActions(): IncomePlanActions = Proxy.newProxyInstance(
    IncomePlanActions::class.java.classLoader,
    arrayOf(IncomePlanActions::class.java),
) { _, method, _ ->
    when (method.name) {
        "toString" -> "UnsupportedIncomeActions"
        else -> throw UnsupportedOperationException(method.name)
    }
} as IncomePlanActions

@Suppress("UNCHECKED_CAST")
private fun unsupportedIncomeDebtActions(): DebtActions = Proxy.newProxyInstance(
    DebtActions::class.java.classLoader,
    arrayOf(DebtActions::class.java),
) { _, method, _ ->
    when (method.name) {
        "toString" -> "UnsupportedIncomeDebtActions"
        else -> throw UnsupportedOperationException(method.name)
    }
} as DebtActions
