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

// 列表信封安装级 currency capability 裁决（空账本放行、同源/冲突/未知键/混币 fail-closed）
// 的测试族（PR#255 R6/R7），自 DebtListViewModelTest 拆出以符合 detekt 类规模门。
class DebtListViewModelCapabilityTest {

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
    fun emptyLedgerResolvesCurrencyFromEnvelopeCapability() = runTest(dispatcher) {
        // PR#255 R6 P1-1：空账本没有 record 级币种可得，但列表信封的安装级 capability
        // （与 record 同源的 installation binding）独立解析 → 首笔创建放行并按 JPY 零小数
        // 口径提交（"1200" → 1200 minor，不再被「等首条 record」循环卡死，也不落 CNY 兜底）。
        val repo = FakeDebtActions(
            listResult = Result.success(emptyList()),
            createResult = Result.success(sampleDebt("created")),
        )
        repo.listCapability = "JPY"
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.debts.isEmpty())
        assertEquals(true, viewModel.state.value.homeCurrencyResolved)
        assertEquals(CurrencyCode.JPY, viewModel.state.value.ledgerHomeCurrency)
        assertEquals(CurrencyCode.JPY, viewModel.state.value.addDraft.homeCurrency)

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1_200L, repo.createDrafts.single().principalAmountCents)
    }

    @Test
    fun envelopeCapabilityMatchingRecordKeepsRecordAuthority() = runTest(dispatcher) {
        // R6 P1-1 同源路径：非空账本 record 级仍是权威，capability 同值到场不改变口径。
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"))),
            createResult = Result.success(sampleDebt("created")),
        )
        repo.listCapability = "JPY"
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals(true, viewModel.state.value.homeCurrencyResolved)
        assertEquals(CurrencyCode.JPY, viewModel.state.value.ledgerHomeCurrency)
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1_200L, repo.createDrafts.single().principalAmountCents)
    }

    @Test
    fun refreshFailureWithResolvedCurrencyKeepsCommandEligible() = runTest(dispatcher) {
        // W2-C 主审 R1 不变量：已知币种后普通列表刷新失败不得禁合法 command —— error 呈现，
        // 但 homeCurrencyResolved 不清空、草稿保留、submitDraft 仍可达创建路径。
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("cny-debt").copy(homeCurrencyCode = "CNY"))),
            createResult = Result.success(sampleDebt("created")),
        )
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()
        assertEquals(true, viewModel.state.value.homeCurrencyResolved)

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        repo.listResult = Result.failure(RuntimeException("offline"))
        viewModel.refresh()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.error != null)
        assertEquals(true, viewModel.state.value.homeCurrencyResolved)
        assertEquals("小王", viewModel.state.value.addDraft.counterpartyLabel)
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1, repo.createDrafts.size)
    }

    @Test
    fun conflictingRecordAndEnvelopeCapabilityFailsClosed() = runTest(dispatcher) {
        // R6 P1-1 冲突裁决：record=JPY 而信封 capability=CNY = binding 漂移（ADR-0061
        // C02 声明 installation currency 不可热切换，漂移即异常）→ fail closed：创建
        // 阻断、草稿不重绑到任一冲突源；漂移消除（同源）后恢复 record 权威放行。
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"))),
            createResult = Result.success(sampleDebt("created")),
        )
        repo.listCapability = "CNY"
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals(false, viewModel.state.value.homeCurrencyResolved)
        assertNull(viewModel.state.value.ledgerHomeCurrency)
        // 不重绑：草稿保持初始兜底（未被猜向任一冲突源）。
        assertEquals(CurrencyCode.CNY, viewModel.state.value.addDraft.homeCurrency)
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.createDrafts.isEmpty())

        repo.listCapability = "JPY"
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals(true, viewModel.state.value.homeCurrencyResolved)
        assertEquals(CurrencyCode.JPY, viewModel.state.value.addDraft.homeCurrency)
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1_200L, repo.createDrafts.single().principalAmountCents)
    }

    @Test
    fun unknownEnvelopeCapabilityFailsClosedOnEmptyLedger() = runTest(dispatcher) {
        // R6 P1-1 未知键裁决：空账本 + 客户端支持集外的 capability（"XXX"）视同缺失 ——
        // 禁止 fromStorageKey 式静默落 CNY（ADR-0061 C03），创建保持阻断。
        val repo = FakeDebtActions(listResult = Result.success(emptyList()))
        repo.listCapability = "XXX"
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals(false, viewModel.state.value.homeCurrencyResolved)
        assertNull(viewModel.state.value.ledgerHomeCurrency)
        assertEquals(CurrencyCode.CNY, viewModel.state.value.addDraft.homeCurrency)
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.createDrafts.isEmpty())
    }

    @Test
    fun mixedRecordCurrenciesFailClosedEvenWhenFirstRowMatchesEnvelope() = runTest(dispatcher) {
        // PR#255 R7-1：installation 漂移后新旧 record 并存 —— 首行（JPY）恰好匹配信封
        // capability（JPY）但次行是 CNY：只验首行的旧逻辑会放行创建（新写入按 JPY 口径
        // 落进混币账本）。全行 distinct>1 = binding 漂移 → fail closed。
        val repo = FakeDebtActions(
            listResult = Result.success(
                listOf(
                    sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"),
                    sampleDebt("cny-debt").copy(homeCurrencyCode = "CNY"),
                ),
            ),
        )
        repo.listCapability = "JPY"
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals(false, viewModel.state.value.homeCurrencyResolved)
        assertNull(viewModel.state.value.ledgerHomeCurrency)
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.createDrafts.isEmpty())
    }

    @Test
    fun unknownRecordCurrencyRowFailsClosed() = runTest(dispatcher) {
        // R7-1 同伴路径：任一 record 未知键（支持集外）→ fail closed，即使其余行与
        // 信封同源 —— 账本里存在客户端无法解释的行时不得放行写。
        val repo = FakeDebtActions(
            listResult = Result.success(
                listOf(
                    sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"),
                    sampleDebt("xxx-debt").copy(homeCurrencyCode = "XXX"),
                ),
            ),
        )
        repo.listCapability = "JPY"
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals(false, viewModel.state.value.homeCurrencyResolved)
        assertNull(viewModel.state.value.ledgerHomeCurrency)
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.createDrafts.isEmpty())
    }

    @Test
    fun knownRecordWithUnknownEnvelopeCapabilityFailsClosed() = runTest(dispatcher) {
        // PR#255 R8-1：capability **在场但未知**（新服务端 VND，客户端支持集外）≠ 缺失 ——
        // 服务端已宣告当前 binding 是客户端无法解释的币种，新写入会被按其盖章；即便 record
        // 已知（CNY）也不得按 record 口径放行（"1200" 按 CNY 解析 120000 → 服务端按 VND
        // 盖章 = 100×）。判定用原始串（blank 才算缺失）。
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("cny-debt").copy(homeCurrencyCode = "CNY"))),
        )
        repo.listCapability = "VND"
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals(false, viewModel.state.value.homeCurrencyResolved)
        assertNull(viewModel.state.value.ledgerHomeCurrency)
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.createDrafts.isEmpty())
    }

    @Test
    fun blankEnvelopeCapabilityKeepsRecordAuthority() = runTest(dispatcher) {
        // R8-1 回归钉：capability **缺失**（blank = 旧服务端无信封字段）时 record 权威维持，
        // 创建放行（与 null 信封同义；不得被「在场未知」分支误伤）。
        val repo = FakeDebtActions(
            listResult = Result.success(listOf(sampleDebt("jpy-debt").copy(homeCurrencyCode = "JPY"))),
            createResult = Result.success(sampleDebt("created")),
        )
        repo.listCapability = ""
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals(true, viewModel.state.value.homeCurrencyResolved)
        assertEquals(CurrencyCode.JPY, viewModel.state.value.ledgerHomeCurrency)
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("1200")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals(1_200L, repo.createDrafts.single().principalAmountCents)
    }
}