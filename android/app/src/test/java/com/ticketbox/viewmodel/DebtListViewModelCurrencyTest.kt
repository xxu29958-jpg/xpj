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

// 账本币种解析（record 级权威重绑、fail-closed 门禁）的测试族，从 DebtListViewModelTest
// 拆出以符合 detekt 类规模门（镜像 GlobalSearch 的拆分类先例）；capability 裁决族见
// DebtListViewModelCapabilityTest。
class DebtListViewModelCurrencyTest {

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

        // 加载未回时用户已按兜底口径输入（"12.01" 在 CNY 是 1201 分，在 JPY
        // 无法精确落到整数 minor）。等值尾零如 "12.00" 应被接受为 JPY 12。
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("12.01")
        gate.complete(Unit)
        advanceUntilIdle()

        val draft = viewModel.state.value.addDraft
        assertEquals(CurrencyCode.JPY, draft.homeCurrency)
        assertEquals("12.01", draft.amountYuanInput)
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
    fun emptyLedgerWithoutCapabilityKeepsCreationBlocked() = runTest(dispatcher) {
        // PR#255 R4 P1 + R6 P1-1：旧服务端不下发信封 capability 时，空账本（如新建
        // JPY/KRW 账本）没有任何可信币种依据 —— 不得按 CNY 兜底声明币种已确认并放开
        // 提交：旧逻辑会把 "1200" 以 120000 minor units 提交，后端解释为 ¥120,000/
        // ₩120,000（100× 资损，ADR-0061 C03 禁默认-CNY 猜测）。保持阻断直到首条记录
        // 带来 record 级权威币种。（新服务端空账本由信封 capability 放行，见
        // emptyLedgerResolvesCurrencyFromEnvelopeCapability。）
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
