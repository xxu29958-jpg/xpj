package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
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
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()
        val state = viewModel.state.value
        assertFalse(state.isLoading)
        assertEquals(1, state.activePlans.size)
        assertEquals(1, state.archivedPlans.size)
        assertEquals(100_000L, state.totalActiveAmountCents)
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
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()
        viewModel.updateDraftLabel("工资")
        viewModel.updateDraftSource(IncomeSourceType.SALARY)
        viewModel.updateDraftAmount("10000")
        viewModel.updateDraftPayDay("10")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1, repo.createCalls)
        assertEquals(IncomeSourceType.SALARY, repo.lastDraft?.sourceType)
        assertEquals(1_000_000L, repo.lastDraft?.amountCents)
        assertEquals(10, repo.lastDraft?.payDay)
        assertEquals(UiText.res(R.string.income_plan_added), viewModel.state.value.flashMessage)
        assertEquals("", viewModel.state.value.addDraft.label) // reset
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
    fun archiveTriggersRepositoryAndFlashMessage() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()
        viewModel.archive("some-id", 1L)
        advanceUntilIdle()
        assertEquals("some-id", repo.lastArchiveId)
        assertEquals(UiText.res(R.string.income_plan_archived), viewModel.state.value.flashMessage)
    }

    @Test
    fun restoreTriggersRepositoryAndFlashMessage() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()
        viewModel.restore("some-id", 1L)
        advanceUntilIdle()
        assertEquals("some-id", repo.lastRestoreId)
        assertEquals(UiText.res(R.string.income_plan_restored), viewModel.state.value.flashMessage)
    }

    @Test
    fun dismissFlashClearsMessage() = runTest(dispatcher) {
        val repo = FakeRepository()
        val viewModel = IncomePlanViewModel(repo)
        advanceUntilIdle()
        viewModel.archive("x", 1L)
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
        // §3 BigDecimal 精度：>2 位小数 HALF_UP 精确进位。"1.005" → 101；旧 Double Math.round 给 100
        // （1.005*100 的 double 是 100.4999… → 100），故此断言会在退回 Double 时变红。
        assertEquals(101L, IncomePlanDraftUi(amountYuanInput = "1.005").parsedAmountCents())
        // 收入计划允许 0（与 DebtList 的 > 0 不同：这里是 >= 0 边界）。
        assertEquals(0L, IncomePlanDraftUi(amountYuanInput = "0").parsedAmountCents())
        // 拒负：极小负额在分空间 HALF_UP 舍入到 0，也按元符号拒，不静默当成 0 元计划。
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
    fun draftIsValidRequiresAllThree() {
        assertTrue(
            IncomePlanDraftUi(label = "x", amountYuanInput = "100", payDayInput = "1").isValid,
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
    ) : IncomePlanActions {
        var createCalls = 0
        var lastDraft: IncomePlanDraft? = null
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

        override suspend fun update(publicId: String, patch: com.ticketbox.data.repository.IncomePlanPatch) =
            Result.success(stub(publicId))

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
