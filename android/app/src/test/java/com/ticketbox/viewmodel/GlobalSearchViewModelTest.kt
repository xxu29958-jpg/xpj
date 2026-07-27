package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.GlobalSearchActions
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class GlobalSearchViewModelTest {
    private fun searchTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun searchesPendingAndConfirmedCachesWithoutPerQueryNetworkCalls() = searchTest {
        val fake = FakeGlobalSearchActions(
            pending = listOf(expense(id = 1, status = "pending", merchant = "SearchCafe Pending")),
            confirmed = listOf(expense(id = 2, status = "confirmed", merchant = "SearchCafe Confirmed")),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("SearchCafe")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(1, fake.fetchPendingCalls)
        assertEquals(1, state.pendingMatchCount)
        assertEquals(1, state.confirmedMatchCount)
        assertEquals(
            listOf(GlobalSearchResultKind.Pending, GlobalSearchResultKind.Confirmed),
            state.results.map { it.kind },
        )

        vm.setQuery("Confirmed")
        advanceUntilIdle()
        assertEquals(1, fake.fetchPendingCalls)
        assertEquals(listOf(2L), vm.uiState.value.results.map { it.expense.id })
    }

    @Test
    fun scopesResultsWithoutChangingTheUnderlyingMatches() = searchTest {
        val fake = FakeGlobalSearchActions(
            pending = listOf(expense(id = 1, status = "pending", merchant = "Family Cafe")),
            confirmed = listOf(expense(id = 2, status = "confirmed", merchant = "Family Cafe")),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("Cafe")
        vm.setScope(GlobalSearchScope.Confirmed)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(1, state.pendingMatchCount)
        assertEquals(1, state.confirmedMatchCount)
        assertEquals(listOf(GlobalSearchResultKind.Confirmed), state.results.map { it.kind })
        assertEquals(listOf(2L), state.results.map { it.expense.id })
    }

    @Test
    fun pendingFailureKeepsConfirmedCacheSearchable() = searchTest {
        val fake = FakeGlobalSearchActions(
            pendingResult = Result.failure(IllegalStateException("pending offline")),
            confirmed = listOf(expense(id = 2, status = "confirmed", merchant = "Local Cafe")),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("Local")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state.pendingLoaded)
        assertEquals(UiText.raw("pending offline"), state.message)
        assertEquals(listOf(2L), state.results.map { it.expense.id })
    }

    @Test
    fun activeLedgerChangeClearsSearchCachesAndReloadsPending() = searchTest {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeGlobalSearchActions(
            activeLedgerFlow = ledgerFlow,
            pending = listOf(expense(id = 1, status = "pending", merchant = "Old Cafe")),
            confirmed = listOf(expense(id = 2, status = "confirmed", merchant = "Old Confirmed")),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("Old")
        advanceUntilIdle()
        assertEquals(listOf(1L, 2L), vm.uiState.value.results.map { it.expense.id })

        fake.pendingResult = Result.success(listOf(expense(id = 3, status = "pending", merchant = "New Cafe")))
        ledgerFlow.value = "family"
        advanceUntilIdle()

        assertEquals(2, fake.fetchPendingCalls)
        assertEquals(0, vm.uiState.value.confirmedMatchCount)
        assertTrue(vm.uiState.value.results.isEmpty())

        vm.setQuery("New")
        advanceUntilIdle()
        assertEquals(listOf(3L), vm.uiState.value.results.map { it.expense.id })
    }

    @Test
    fun parsesAmountQueryInCachedHomeCurrencySoJpyRowHits() = searchTest {
        // JPY-home 账本：搜索 "1200" 必须按零小数 home 解析为 minor 1200（而非
        // 120000），否则永远碰不到 amountCents/originalAmountMinor = 1200 的行。
        val fake = FakeGlobalSearchActions(
            confirmed = listOf(
                expense(id = 1, status = "confirmed", merchant = "Tokyo Cafe", amountCents = 1_200L)
                    .copy(
                        homeCurrency = CurrencyCode.JPY,
                        originalCurrencyCode = CurrencyCode.JPY,
                        originalAmountMinor = 1_200L,
                    ),
            ),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("1200")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(listOf(1L), state.results.map { it.expense.id })
        // 命中走的是金额腿，不是文本腿。
        assertEquals(
            UiText.res(R.string.global_search_field_amount),
            state.results.single().matchedField,
        )
    }

    @Test
    fun amountQueryHitsForeignOriginalLegInItsOwnCurrency() = searchTest {
        // PR#255 P2 双腿：JPY-home 行、USD 原币 12.50（minor 1250）—— 查询 "12.50"
        // 按 home(JPY) 解析不出，但按行自身 originalCurrency(USD) 解析原币腿命中。
        val jpyHomeUsdRow = expense(id = 1, status = "confirmed", merchant = "Tokyo Books", amountCents = 18_518L)
            .copy(
                homeCurrency = CurrencyCode.JPY,
                originalCurrencyCode = CurrencyCode.USD,
                originalAmountMinor = 1_250L,
            )
        // CNY-home 行、JPY 原币 1200 —— 查询 "1200" 按 home(CNY) 是 120000 碰不到，
        // 按 originalCurrency(JPY) 解析原币腿命中。
        val cnyHomeJpyRow = expense(id = 2, status = "confirmed", merchant = "Osaka Mart", amountCents = 5_500L)
            .copy(originalCurrencyCode = CurrencyCode.JPY, originalAmountMinor = 1_200L)
        val fake = FakeGlobalSearchActions(confirmed = listOf(jpyHomeUsdRow, cnyHomeJpyRow))
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("12.50")
        advanceUntilIdle()
        assertEquals(listOf(1L), vm.uiState.value.results.map { it.expense.id })

        vm.setQuery("1200")
        advanceUntilIdle()
        assertEquals(listOf(2L), vm.uiState.value.results.map { it.expense.id })
    }

    @Test
    fun amountQueryStillParsesAsCentsUnderCnyHomeCache() = searchTest {
        // 回归：2 位小数 home 缓存下 "12" 仍解析为 1200 分并命中金额腿。
        val fake = FakeGlobalSearchActions(
            confirmed = listOf(expense(id = 2, status = "confirmed", merchant = "Local Cafe", amountCents = 1_200L)),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("12")
        advanceUntilIdle()
        assertEquals(listOf(2L), vm.uiState.value.results.map { it.expense.id })
    }

    @Test
    fun fractionQueryUnderZeroDecimalHomeFallsBackToTextMatching() = searchTest {
        // JPY-home 下 "12.5" 不解析为金额（拒绝静默进位）；文本字段也不含它 → 无结果。
        val fake = FakeGlobalSearchActions(
            confirmed = listOf(
                expense(id = 1, status = "confirmed", merchant = "Tokyo Cafe", amountCents = 1_250L)
                    .copy(
                        homeCurrency = CurrencyCode.JPY,
                        originalCurrencyCode = CurrencyCode.JPY,
                        originalAmountMinor = 1_250L,
                    ),
            ),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("12.5")
        advanceUntilIdle()
        assertTrue(vm.uiState.value.results.isEmpty())
    }

    @Test
    fun formattedAmountQueryHitsRowViaCachedPerCurrencyParse() = searchTest {
        // PR#255 P2-1/P2-2：query 对每个支持币种只解析一次（含符号/locale 分隔符
        // 归一化）缓存进 SearchCriteria，逐行匹配复用 —— 从 Android 格式化器复制的
        // 显示值可直接命中对应币种腿。
        // KRW-home 行：查 "₩1,200"（ko-KR 分组显示值）按 KRW 解析命中 home 腿。
        val krwHomeRow = expense(id = 1, status = "confirmed", merchant = "Seoul Deli", amountCents = 1_200L)
            .copy(
                homeCurrency = CurrencyCode.KRW,
                originalCurrencyCode = CurrencyCode.KRW,
                originalAmountMinor = 1_200L,
            )
        // CNY-home 行、EUR 原币 1234.50（minor 123450）：查 de-DE 显示值 "€1.234,50"
        // 按 EUR 解析原币腿命中（home CNY 解析不出该文本）。
        val cnyHomeEurRow = expense(id = 2, status = "confirmed", merchant = "Berlin Mart", amountCents = 8_600L)
            .copy(originalCurrencyCode = CurrencyCode.EUR, originalAmountMinor = 123_450L)
        val fake = FakeGlobalSearchActions(confirmed = listOf(krwHomeRow, cnyHomeEurRow))
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("₩1,200")
        advanceUntilIdle()
        assertEquals(listOf(1L), vm.uiState.value.results.map { it.expense.id })

        vm.setQuery("€1.234,50")
        advanceUntilIdle()
        assertEquals(listOf(2L), vm.uiState.value.results.map { it.expense.id })

        // 非数字 query 短路为空金额表：金额腿无命中，走纯文本匹配。
        vm.setQuery("Berlin")
        advanceUntilIdle()
        assertEquals(listOf(2L), vm.uiState.value.results.map { it.expense.id })
    }

    @Test
    fun stalePendingResponseAfterLedgerChangeIsIgnored() = searchTest {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val firstResponse = CompletableDeferred<Result<List<Expense>>>()
        val secondResponse = CompletableDeferred<Result<List<Expense>>>()
        val fake = FakeGlobalSearchActions(activeLedgerFlow = ledgerFlow)
        var fetchIndex = 0
        fake.fetchPendingResponder = {
            fetchIndex += 1
            if (fetchIndex == 1) firstResponse.await() else secondResponse.await()
        }
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("Cafe")
        ledgerFlow.value = "family"
        advanceUntilIdle()

        firstResponse.complete(Result.success(listOf(expense(id = 4, status = "pending", merchant = "Old Cafe"))))
        advanceUntilIdle()
        assertTrue(vm.uiState.value.results.isEmpty())

        secondResponse.complete(Result.success(listOf(expense(id = 5, status = "pending", merchant = "New Cafe"))))
        advanceUntilIdle()

        assertEquals(2, fake.fetchPendingCalls)
        assertEquals(listOf(5L), vm.uiState.value.results.map { it.expense.id })
    }
}
