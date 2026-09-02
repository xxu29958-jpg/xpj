package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtListPage
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
    fun amountSeedsWhenCurrencyResolutionCompletesAfterOpen() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300))
        val gate = CompletableDeferred<Unit>()
        val debts = CapabilityDebtActions()
        debts.listDebtsGate = { gate.await() }
        val viewModel = IncomePlanEditViewModel(repo, debts)
        advanceUntilIdle()

        // 弱网路径：列表已有缓存、编辑 VM 刚建立、币种解析未归时点行——先开会话（无币种）。
        viewModel.openEdit(plan)
        viewModel.state.value.also { state ->
            assertNotNull(state.session)
            assertNull(state.session?.draft?.homeCurrency)
            assertEquals("", state.session?.draft?.amountYuanInput)
            // 解析未归期间对 UI 亮「正在准备金额」，不留永久空金额。
            assertTrue(state.currencyPending)
        }

        gate.complete(Unit)
        advanceUntilIdle()

        viewModel.state.value.also { state ->
            assertNotNull(state.session)
            assertEquals(CurrencyCode.CNY, state.session?.draft?.homeCurrency)
            assertEquals("123.00", state.session?.draft?.amountYuanInput)
            assertFalse(state.currencyPending)
        }
    }

    @Test
    fun retryCurrencyResolutionSeedsDraftAfterRecovery() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300))
        // 首次解析 fail closed：信封 capability 是未知码（"XXX"）→ 无币种；恢复后重试补种子。
        val debts = CapabilityDebtActions(
            page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "XXX"),
        )
        val viewModel = IncomePlanEditViewModel(repo, debts)
        advanceUntilIdle()

        viewModel.openEdit(plan)
        viewModel.state.value.also { state ->
            assertNotNull(state.session)
            assertNull(state.session?.draft?.homeCurrency)
            assertEquals("", state.session?.draft?.amountYuanInput)
            assertFalse(state.currencyPending)
        }

        debts.page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "CNY")
        viewModel.retryCurrencyResolution()
        advanceUntilIdle()

        viewModel.state.value.also { state ->
            assertNotNull(state.session)
            assertEquals(CurrencyCode.CNY, state.session?.draft?.homeCurrency)
            assertEquals("123.00", state.session?.draft?.amountYuanInput)
            assertFalse(state.currencyPending)
        }
    }

    @Test
    fun dismissDuringSubmitKeepsSessionUntilResult() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300))
        val gate = CompletableDeferred<Unit>()
        repo.updateGate = { gate.await() }
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.openEdit(plan)

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
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(planA, planB), 17_300))
        val gate = CompletableDeferred<Unit>()
        repo.updateGate = { gate.await() }
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.openEdit(planA)
        viewModel.submit()
        advanceUntilIdle()

        // busy 期间点开另一行不切 target：A 的迟到结果不得盖到 B 的会话上。
        viewModel.openEdit(planB)
        assertEquals("p1", viewModel.state.value.session?.publicId)

        gate.complete(Unit)
        advanceUntilIdle()
        assertTrue(viewModel.state.value.succeeded)
        assertEquals("p1", viewModel.state.value.session?.publicId)
    }
}
