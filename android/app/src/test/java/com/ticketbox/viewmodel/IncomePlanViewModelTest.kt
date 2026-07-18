package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.data.repository.IncomePlanPatch
import com.ticketbox.data.repository.IncomePlanSaveOutcome
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import java.time.YearMonth
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
    fun initRefreshSharesCurrentMonthExpectedAndHistoricalSummary() = runTest(dispatcher) {
        val repo = FakeRepository(
            active = IncomePlanListing(
                plans = listOf(
                    plan("monthly", 100_000, status = IncomePlanStatus.ACTIVE),
                    plan(
                        "current-once",
                        25_000,
                        status = IncomePlanStatus.ACTIVE,
                        frequency = IncomeFrequency.ONE_TIME,
                        incomeMonth = "2026-07",
                    ),
                    plan(
                        "history-once",
                        50_000,
                        status = IncomePlanStatus.ACTIVE,
                        frequency = IncomeFrequency.ONE_TIME,
                        incomeMonth = "2026-06",
                    ),
                    plan(
                        "future-once",
                        75_000,
                        status = IncomePlanStatus.ACTIVE,
                        frequency = IncomeFrequency.ONE_TIME,
                        incomeMonth = "2026-08",
                    ),
                ),
                // API total is received-to-date, not the expected-month amount.
                totalActiveAmountCents = 50_000,
            ),
            archived = listOf(plan("p2", 50_000, status = IncomePlanStatus.ARCHIVED)),
        )
        val viewModel = IncomePlanViewModel(
            repo,
            currentMonthProvider = { YearMonth.of(2026, 7) },
        )
        advanceUntilIdle()
        val state = viewModel.state.value
        assertFalse(state.isLoading)
        assertEquals(4, state.activePlans.size)
        assertEquals(1, state.archivedPlans.size)
        assertEquals(2, state.currentMonthSummary.effectivePlanCount)
        assertEquals(125_000L, state.currentMonthSummary.expectedAmountCents)
        assertEquals(1, state.currentMonthSummary.historicalRecordCount)
    }

    @Test
    fun submitDraftValidatesBeforeNetworkCall() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo)
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
        var dataChangeCount = 0
        val viewModel = IncomePlanViewModel(
            repository = repo,
            onDataChanged = { dataChangeCount += 1 },
        )
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
        assertEquals(1, dataChangeCount)
    }

    @Test
    fun submitOneTimeDraftSendsIncomeMonth() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo)
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
    fun shiftDraftIncomeMonthKeepsInternalWireValue() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo)
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
        val viewModel = IncomePlanViewModel(repo)
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
        val viewModel = IncomePlanViewModel(repo)
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
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()
        viewModel.updateDraftLabel("x")
        viewModel.updateDraftAmount("100")
        viewModel.updateDraftPayDay("1")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertFalse(viewModel.state.value.addSucceeded)
    }

    @Test
    fun editMonthlyPlanPreloadsDraftAndSendsOneTimePatchWithOccToken() = runTest(dispatcher) {
        val baseline = plan("salary", 100_000).copy(
            label = "工资",
            payDay = 10,
            rowVersion = 7L,
        )
        val saved = baseline.copy(
            label = "项目尾款",
            sourceType = IncomeSourceType.FREELANCE,
            frequency = IncomeFrequency.ONE_TIME,
            incomeMonth = "2026-08",
            amountCents = 250_000L,
            payDay = 28,
            rowVersion = 8L,
        )
        val repo = FakeRepository(
            active = IncomePlanListing(listOf(baseline), baseline.amountCents),
            updateResult = Result.success(IncomePlanSaveOutcome.Synced(saved)),
        )
        val viewModel = IncomePlanViewModel(
            repository = repo,
            currentMonthProvider = { YearMonth.of(2026, 7) },
        )
        advanceUntilIdle()

        assertTrue(viewModel.beginEdit(baseline))
        assertEquals("工资", viewModel.state.value.addDraft.label)
        assertEquals(100_000L, viewModel.state.value.addDraft.parsedAmountCents())
        assertEquals("2026-07", viewModel.state.value.addDraft.incomeMonthInput)
        viewModel.updateDraftLabel("项目尾款")
        viewModel.updateDraftSource(IncomeSourceType.FREELANCE)
        viewModel.updateDraftFrequency(IncomeFrequency.ONE_TIME)
        viewModel.updateDraftIncomeMonth("2026-08")
        viewModel.updateDraftAmount("2500")
        viewModel.updateDraftPayDay("28")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertEquals(1, repo.updateCalls)
        assertEquals(baseline, repo.lastUpdateBaseline)
        assertEquals(7L, repo.lastUpdatePatch?.expectedRowVersion)
        assertEquals(IncomeFrequency.ONE_TIME, repo.lastUpdatePatch?.frequency)
        assertEquals("2026-08", repo.lastUpdatePatch?.incomeMonth)
        assertEquals(250_000L, repo.lastUpdatePatch?.amountCents)
        assertTrue(viewModel.state.value.editSucceeded)
        assertEquals(UiText.res(R.string.income_plan_updated), viewModel.state.value.flashMessage)
        assertEquals(saved, viewModel.state.value.activePlans.single())
        assertEquals(0, viewModel.state.value.currentMonthSummary.effectivePlanCount)
    }

    @Test
    fun editOneTimePlanToMonthlyKeepsQueuedProjectionAndClearsMonthShape() = runTest(dispatcher) {
        val baseline = plan(
            id = "bonus",
            amountCents = 50_000L,
            frequency = IncomeFrequency.ONE_TIME,
            incomeMonth = "2026-07",
        ).copy(label = "奖金", rowVersion = 11L)
        val optimistic = baseline.copy(
            label = "固定津贴",
            frequency = IncomeFrequency.MONTHLY,
            incomeMonth = null,
            amountCents = 60_000L,
            payDay = 15,
        )
        var dataChangeCount = 0
        val repo = FakeRepository(
            active = IncomePlanListing(listOf(baseline), baseline.amountCents),
            updateResult = Result.success(IncomePlanSaveOutcome.Queued(optimistic)),
        )
        val viewModel = IncomePlanViewModel(
            repository = repo,
            currentMonthProvider = { YearMonth.of(2026, 7) },
            onDataChanged = { dataChangeCount += 1 },
        )
        advanceUntilIdle()

        assertTrue(viewModel.beginEdit(baseline))
        viewModel.updateDraftLabel("固定津贴")
        viewModel.updateDraftFrequency(IncomeFrequency.MONTHLY)
        viewModel.updateDraftAmount("600")
        viewModel.updateDraftPayDay("15")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertEquals(11L, repo.lastUpdatePatch?.expectedRowVersion)
        assertEquals(IncomeFrequency.MONTHLY, repo.lastUpdatePatch?.frequency)
        assertNull(repo.lastUpdatePatch?.incomeMonth)
        assertEquals(optimistic, viewModel.state.value.activePlans.single())
        assertEquals(1, viewModel.state.value.currentMonthSummary.effectivePlanCount)
        assertEquals(60_000L, viewModel.state.value.currentMonthSummary.expectedAmountCents)
        assertEquals(UiText.res(R.string.income_plan_update_queued), viewModel.state.value.flashMessage)
        assertEquals(MessageTone.Info, viewModel.state.value.flashTone)
        assertTrue(viewModel.state.value.editSucceeded)
        assertEquals(1, dataChangeCount)
    }

    @Test
    fun editFailureKeepsEditorDraftAndSurfacesError() = runTest(dispatcher) {
        val baseline = plan("salary", 100_000L)
        val repo = FakeRepository(
            active = IncomePlanListing(listOf(baseline), baseline.amountCents),
            updateResult = Result.failure(RuntimeException("版本冲突")),
        )
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()

        assertTrue(viewModel.beginEdit(baseline))
        viewModel.updateDraftLabel("调整后工资")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertEquals("调整后工资", viewModel.state.value.addDraft.label)
        assertEquals(baseline, viewModel.state.value.editingPlan)
        assertEquals(UiText.raw("版本冲突"), viewModel.state.value.addDraft.validationError)
        assertFalse(viewModel.state.value.isSubmitting)
        assertFalse(viewModel.state.value.editSucceeded)
    }

    @Test
    fun viewerCannotOpenIncomePlanEditor() = runTest(dispatcher) {
        val baseline = plan("salary", 100_000L)
        val repo = FakeRepository(
            active = IncomePlanListing(listOf(baseline), baseline.amountCents),
            canModify = false,
        )
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()

        assertFalse(viewModel.beginEdit(baseline))
        assertNull(viewModel.state.value.editingPlan)
        assertEquals(UiText.res(R.string.common_readonly_ledger), viewModel.state.value.error)
        assertEquals(0, repo.updateCalls)
    }

    @Test
    fun archiveTriggersRepositoryAndFlashMessage() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()
        viewModel.setArchived("some-id", 1L, archived = true)
        advanceUntilIdle()
        assertEquals("some-id", repo.lastArchiveId)
        assertEquals(UiText.res(R.string.income_plan_archived), viewModel.state.value.flashMessage)
    }

    @Test
    fun restoreTriggersRepositoryAndFlashMessage() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()
        viewModel.setArchived("some-id", 1L, archived = false)
        advanceUntilIdle()
        assertEquals("some-id", repo.lastRestoreId)
        assertEquals(UiText.res(R.string.income_plan_restored), viewModel.state.value.flashMessage)
    }

    @Test
    fun dismissFlashClearsMessage() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()
        viewModel.setArchived("x", 1L, archived = true)
        advanceUntilIdle()
        viewModel.dismissFlash()
        assertNull(viewModel.state.value.flashMessage)
    }

    @Test
    fun viewerRoleBlocksWriteAttempts() = runTest(dispatcher) {
        val repo = FakeRepository(canModify = false)
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()
        assertFalse(viewModel.state.value.canModify)
    }

    @Test
    fun draftAmountParsing() {
        val draft = IncomePlanDraftUi(amountYuanInput = "123.45")
        assertEquals(12345L, draft.parsedAmountCents())
        // Surplus fractional precision is invalid; money input is never rounded.
        assertEquals(null, IncomePlanDraftUi(amountYuanInput = "1.005").parsedAmountCents())
        // 收入计划允许 0（与 DebtList 的 > 0 不同：这里是 >= 0 边界）。
        assertEquals(0L, IncomePlanDraftUi(amountYuanInput = "0").parsedAmountCents())
        // Every negative input is rejected explicitly, including sub-minor values.
        assertEquals(null, IncomePlanDraftUi(amountYuanInput = "-0.004").parsedAmountCents())
        // 溢出 Long 安全返回 null（旧 Double Math.round 会回 Long.MAX 垃圾值）。
        assertEquals(null, IncomePlanDraftUi(amountYuanInput = "99999999999999999999").parsedAmountCents())
        assertEquals(null, IncomePlanDraftUi(amountYuanInput = "abc").parsedAmountCents())
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
            IncomePlanDraftUi(label = "x", amountYuanInput = "100", payDayInput = "1").isValid,
        )
        assertTrue(
            IncomePlanDraftUi(
                label = "x",
                frequency = IncomeFrequency.ONE_TIME,
                incomeMonthInput = "2026-06",
                amountYuanInput = "100",
                payDayInput = "1",
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
        frequency: IncomeFrequency = IncomeFrequency.MONTHLY,
        incomeMonth: String? = null,
    ) = IncomePlan(
        publicId = id,
        label = "label-$id",
        sourceType = IncomeSourceType.SALARY,
        frequency = frequency,
        incomeMonth = incomeMonth,
        amountCents = amountCents,
        payDay = 1,
        status = status,
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-01T00:00:00Z",
        rowVersion = 1L,
        archivedAt = if (status == IncomePlanStatus.ARCHIVED) "2026-05-15T00:00:00Z" else null,
    )

    private class FakeRepository(
        private val active: IncomePlanListing = IncomePlanListing(emptyList(), 0L),
        private val archived: List<IncomePlan> = emptyList(),
        private val canModify: Boolean = true,
        private val createResult: Result<IncomePlan>? = null,
        private val updateResult: Result<IncomePlanSaveOutcome>? = null,
    ) : IncomePlanActions {
        var createCalls = 0
        var updateCalls = 0
        var lastDraft: IncomePlanDraft? = null
        var lastUpdateBaseline: IncomePlan? = null
        var lastUpdatePatch: IncomePlanPatch? = null
        var lastArchiveId: String? = null
        var lastRestoreId: String? = null

        override fun canModifyLedger(): Boolean = canModify

        override suspend fun listActive(): Result<IncomePlanListing> = Result.success(active)

        override suspend fun listIncluding(status: IncomePlanStatus): Result<List<IncomePlan>> =
            Result.success(archived)

        override suspend fun create(draft: IncomePlanDraft): Result<IncomePlan> {
            createCalls += 1
            lastDraft = draft
            return createResult ?: Result.success(stub(draft.label))
        }

        override suspend fun update(publicId: String, patch: IncomePlanPatch) =
            Result.success(stub(publicId))

        override suspend fun updateAllowingOffline(
            baseline: IncomePlan,
            patch: IncomePlanPatch,
        ): Result<IncomePlanSaveOutcome> {
            updateCalls += 1
            lastUpdateBaseline = baseline
            lastUpdatePatch = patch
            return updateResult ?: Result.success(
                IncomePlanSaveOutcome.Synced(baseline.copy(rowVersion = baseline.rowVersion + 1L)),
            )
        }

        override suspend fun archive(publicId: String, expectedRowVersion: Long): Result<IncomePlan> {
            lastArchiveId = publicId
            return Result.success(stub(publicId, IncomePlanStatus.ARCHIVED))
        }

        override suspend fun restore(publicId: String, expectedRowVersion: Long): Result<IncomePlan> {
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
