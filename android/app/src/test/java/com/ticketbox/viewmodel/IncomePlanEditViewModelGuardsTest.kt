package com.ticketbox.viewmodel

import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.domain.model.CurrencyCode
import kotlinx.coroutines.CompletableDeferred
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

/**
 * W2-C 收入编辑守卫窄回归：busy（在途提交）期间 Back/手势退场与切换 target 被吞——迟到结果
 * 只归属原会话；币种解析 fail closed，晚解析/手动重试恢复时给已开会话补种子（不留永久空金额）。
 * 共享夹具见 IncomePlanEditViewModelFixtures。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class IncomePlanEditViewModelGuardsTest {

    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun editUsesThePlansRecordedCurrencyImmediately() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L).copy(homeCurrencyCode = "JPY")
        val repo = FakeIncomePlanEditRepository()
        val viewModel = IncomePlanEditViewModel(repo)
        advanceUntilIdle()
        viewModel.openEdit(plan, "2026-09")
        val state = viewModel.state.value
        assertEquals(CurrencyCode.JPY, state.session?.draft?.homeCurrency)
        assertEquals("12300", state.session?.draft?.amountYuanInput)
        assertFalse(state.currencyPending)
    }

    @Test
    fun retryFillsUnknownCachedCurrencyFromTheSamePlanVersion() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L).copy(homeCurrencyCode = "JPY")
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300,
            month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0, homeCurrencyCode = "CNY"))
        val gate = CompletableDeferred<Unit>()
        repo.listGate = { gate.await() }
        val viewModel = IncomePlanEditViewModel(repo)
        advanceUntilIdle()
        viewModel.openEdit(plan.copy(homeCurrencyCode = null), "2026-09")
        assertNull(viewModel.state.value.session?.draft?.homeCurrency)
        assertEquals("", viewModel.state.value.session?.draft?.amountYuanInput)
        viewModel.retryCurrencyResolution()
        advanceUntilIdle()
        assertTrue(viewModel.state.value.currencyPending)
        gate.complete(Unit)
        advanceUntilIdle()
        val session = assertNotNull(viewModel.state.value.session)
        assertEquals(CurrencyCode.JPY, session.draft.homeCurrency)
        assertEquals("12300", session.draft.amountYuanInput)
        assertEquals("JPY", session.baseline.homeCurrencyCode)
        assertFalse(viewModel.state.value.currencyPending)
    }

    @Test
    fun retryDoesNotBorrowCurrencyFromANewerPlanVersion() = runTest(dispatcher) {
        val baseline = editPlan("p1", 12_300, rowVersion = 7L).copy(homeCurrencyCode = null)
        val current = baseline.copy(rowVersion = 8L, homeCurrencyCode = "JPY")
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(current), 12_300,
            month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0, homeCurrencyCode = "CNY"))
        val viewModel = IncomePlanEditViewModel(repo)
        advanceUntilIdle()
        viewModel.openEdit(baseline, "2026-09")
        viewModel.retryCurrencyResolution()
        advanceUntilIdle()
        val session = assertNotNull(viewModel.state.value.session)
        assertEquals(7L, session.baselineRowVersion)
        assertNull(session.draft.homeCurrency)
        assertNotNull(session.draft.validationError)
        assertTrue(repo.updateCalls.isEmpty())
    }

    @Test
    fun dismissDuringSubmitKeepsSessionUntilResult() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0, homeCurrencyCode = "CNY"))
        val gate = CompletableDeferred<Unit>()
        repo.updateGate = { gate.await() }
        val viewModel = IncomePlanEditViewModel(repo)
        advanceUntilIdle()
        viewModel.openEdit(plan, "2026-09")

        viewModel.submit()
        advanceUntilIdle()
        assertTrue(viewModel.state.value.isSubmitting)

        // busy 期间的 Back/手势退场必须被吞：会话与提交中标记保留，在途结果仍归属原会话。
        viewModel.dismiss()
        assertNotNull(viewModel.state.value.session)
        assertTrue(viewModel.state.value.isSubmitting)

        gate.complete(Unit)
        advanceUntilIdle()
        assertTrue(viewModel.state.value.succeeded)
        assertEquals("p1", viewModel.state.value.session?.publicId)
    }

    @Test
    fun openEditDuringSubmitKeepsOriginalSession() = runTest(dispatcher) {
        val planA = editPlan("p1", 12_300, rowVersion = 7L)
        val planB = editPlan("p2", 5_000, rowVersion = 2L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(planA, planB), 17_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0, homeCurrencyCode = "CNY"))
        val gate = CompletableDeferred<Unit>()
        repo.updateGate = { gate.await() }
        val viewModel = IncomePlanEditViewModel(repo)
        advanceUntilIdle()
        viewModel.openEdit(planA, "2026-09")
        viewModel.submit()
        advanceUntilIdle()

        // busy 期间点开另一行不切 target：A 的迟到结果不得盖到 B 的会话上。
        viewModel.openEdit(planB, "2026-09")
        assertEquals("p1", viewModel.state.value.session?.publicId)

        gate.complete(Unit)
        advanceUntilIdle()
        assertTrue(viewModel.state.value.succeeded)
        assertEquals("p1", viewModel.state.value.session?.publicId)
    }
}
