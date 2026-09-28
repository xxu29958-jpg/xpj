package com.ticketbox.viewmodel

import com.ticketbox.domain.model.CurrencyCode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals

@OptIn(ExperimentalCoroutinesApi::class)
class IncomeDraftCurrencyTest {
    @Test
    fun `refresh preserves entered money and a new draft uses the latest confirmed default`() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val repo = FakeIncomePlanCreateRepository().apply { active = active.copy(homeCurrencyCode = "JPY") }
            val listing = IncomePlanViewModel(repo)
            val model = IncomePlanCreateViewModel(repo)
            advanceUntilIdle()
            model.openOriginal(repo)
            model.updateDraftField(IncomePlanDraftField.Amount, "1200")
            repo.active = repo.active.copy(homeCurrencyCode = "CNY")
            listing.refresh()
            advanceUntilIdle()
            assertEquals("CNY", listing.state.value.forecastCurrencyCode)
            assertEquals(CurrencyCode.JPY, model.state.value.session?.draft?.homeCurrency)
            assertEquals("1200", model.state.value.session?.draft?.amountYuanInput)
            assertEquals(1200L, model.state.value.session?.draft?.parsedAmountCents())
            model.cancel()
            model.openOriginal(repo)
            assertEquals(CurrencyCode.CNY, model.state.value.session?.draft?.homeCurrency)
            assertEquals("", model.state.value.session?.draft?.amountYuanInput)
        } finally {
            Dispatchers.resetMain()
        }
    }
}
