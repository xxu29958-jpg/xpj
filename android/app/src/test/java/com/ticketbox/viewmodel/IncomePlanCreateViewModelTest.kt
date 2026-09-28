package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class IncomePlanCreateViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun submitDraftValidatesBeforeNetworkCall() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository()
        val viewModel = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        viewModel.openOriginal(repo)
        viewModel.updateDraftLabel("")
        viewModel.updateDraftAmount("abc")
        viewModel.updateDraftPayDay("99")
        viewModel.submit()
        advanceUntilIdle()
        assertEquals(0, repo.createCalls)
        assertNotNull(viewModel.state.value.session?.draft?.validationError)
    }

    @Test
    fun submitDraftClosesOnlyAfterDurablePublicationAndDoesNotInventAcceptance() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository()
        val viewModel = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        viewModel.openOriginal(repo)
        viewModel.updateDraftLabel("工资")
        viewModel.updateDraftSource(IncomeSourceType.SALARY)
        viewModel.updateDraftAmount("10000")
        viewModel.updateDraftPayDay("10")
        viewModel.submit()
        advanceUntilIdle()
        assertEquals(1, repo.createCalls)
        assertEquals(0, repo.listActiveCalls)
        assertEquals(1L, viewModel.state.value.publishedRowId)
        assertTrue(repo.active.plans.isEmpty())
        assertEquals(IncomeSourceType.SALARY, repo.lastDraft?.sourceType)
        assertEquals(IncomeFrequency.ONE_TIME, repo.lastDraft?.frequency)
        assertNotNull(repo.lastDraft?.incomeMonth)
        assertEquals(1_000_000L, repo.lastDraft?.amountCents)
        assertEquals(10, repo.lastDraft?.payDay)
        assertEquals(UiText.res(R.string.income_plan_submission_saved), viewModel.state.value.flashMessage)
        assertNull(viewModel.state.value.session) // Room now owns the accepted intent
    }

    @Test
    fun submitOneTimeDraftSendsIncomeMonth() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository()
        val viewModel = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        viewModel.openOriginal(repo)
        viewModel.updateDraftLabel("项目尾款")
        viewModel.updateDraftSource(IncomeSourceType.FREELANCE)
        viewModel.updateDraftFrequency(IncomeFrequency.ONE_TIME)
        viewModel.updateDraftIncomeMonth("2026-06")
        viewModel.updateDraftAmount("2500")
        viewModel.updateDraftPayDay("28")
        viewModel.submit()
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
        val repo = FakeIncomePlanCreateRepository().apply { active = active.copy(homeCurrencyCode = "JPY") }
        val viewModel = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        viewModel.openOriginal(repo)

        viewModel.updateDraftLabel("工资")
        viewModel.updateDraftAmount("1200")
        viewModel.updateDraftPayDay("10")
        viewModel.submit()
        advanceUntilIdle()

        assertEquals(1, repo.createCalls)
        assertEquals(1_200L, repo.lastDraft?.amountCents)
    }

    @Test
    fun submitDraftBlockedWhenCapabilityUnsupported() = runTest(dispatcher) {
        // R12-D：capability 在支持集外（新版服务端币种）→ 草稿 homeCurrency=null → 禁写 +
        // 明示文案，create 不可达。
        val repo = FakeIncomePlanCreateRepository().apply { active = active.copy(homeCurrencyCode = "VND") }
        val viewModel = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        viewModel.openOriginal(repo)

        assertNull(viewModel.state.value.session?.draft?.homeCurrency)
        viewModel.updateDraftLabel("工资")
        viewModel.updateDraftAmount("1200")
        viewModel.updateDraftPayDay("10")
        viewModel.submit()
        advanceUntilIdle()

        assertEquals(0, repo.createCalls)
        assertEquals(
            UiText.res(R.string.currency_unconfirmed_write_blocked),
            viewModel.state.value.session?.draft?.validationError,
        )
    }

    @Test
    fun updateDraftAmountReportsParseFailureImmediately() = runTest(dispatcher) {
        // PR#255 R14-2：JPY 账本输 "12.50" 即时报解析失败（不再静默 isValid=false）；改合法即清。
        val repo = FakeIncomePlanCreateRepository().apply { active = active.copy(homeCurrencyCode = "JPY") }
        val viewModel = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        viewModel.openOriginal(repo)

        viewModel.updateDraftAmount("12.50")
        assertEquals(
            UiText.res(R.string.expense_edit_amount_invalid),
            viewModel.state.value.session?.draft?.validationError,
        )

        viewModel.updateDraftAmount("1250")
        assertNull(viewModel.state.value.session?.draft?.validationError)
    }

    @Test
    fun shiftDraftIncomeMonthKeepsInternalWireValue() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository()
        val viewModel = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        viewModel.openOriginal(repo)
        viewModel.updateDraftIncomeMonth("2026-06")

        viewModel.shiftDraftIncomeMonth(-1L)
        assertEquals("2026-05", viewModel.state.value.session?.draft?.incomeMonthInput)

        viewModel.shiftDraftIncomeMonth(2L)
        assertEquals("2026-07", viewModel.state.value.session?.draft?.incomeMonthInput)
    }

    @Test
    fun submitDraftSurfacesRepositoryError() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository(createResult = Result.failure(RuntimeException("网络异常")))
        val viewModel = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        viewModel.openOriginal(repo)
        viewModel.updateDraftLabel("x")
        viewModel.updateDraftAmount("100")
        viewModel.updateDraftPayDay("1")
        viewModel.submit()
        advanceUntilIdle()
        assertEquals(UiText.raw("网络异常"), viewModel.state.value.session?.draft?.validationError)
        assertFalse(viewModel.state.value.isSubmitting)
    }

    @Test
    fun publicationSuccessSetsOriginalRowAckThenConsumeClears() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository()
        val viewModel = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        viewModel.openOriginal(repo)
        viewModel.updateDraftLabel("工资")
        viewModel.updateDraftAmount("10000")
        viewModel.updateDraftPayDay("10")
        viewModel.submit()
        advanceUntilIdle()

        assertEquals(1L, viewModel.state.value.publishedRowId)
        viewModel.consumePublished()
        assertNull(viewModel.state.value.publishedRowId)
    }

    @Test
    fun publicationFailureLeavesOriginalRowAckEmpty() = runTest(dispatcher) {
        // A backend failure must NOT signal the screen to close — the sheet stays open with its
        // validationError instead of vanishing while the user believes the plan was created.
        val repo = FakeIncomePlanCreateRepository(createResult = Result.failure(RuntimeException("网络异常")))
        val viewModel = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        viewModel.openOriginal(repo)
        viewModel.updateDraftLabel("x")
        viewModel.updateDraftAmount("100")
        viewModel.updateDraftPayDay("1")
        viewModel.submit()
        advanceUntilIdle()

        assertNull(viewModel.state.value.publishedRowId)
    }

}
