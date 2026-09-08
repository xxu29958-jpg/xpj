package com.ticketbox.viewmodel

import com.ticketbox.domain.model.CurrencyCode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals

class IncomeDraftCurrencyTest {
    @Test
    fun `refresh preserves entered money and a new draft uses the latest confirmed default`() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val repo = FakeIncomePlanEditRepository().apply { active = active.copy(homeCurrencyCode = "JPY") }
            val model = IncomePlanViewModel(repo)
            advanceUntilIdle()
            model.updateDraftField(IncomePlanDraftField.Amount, "1200")
            repo.active = repo.active.copy(homeCurrencyCode = "CNY")
            model.refresh()
            advanceUntilIdle()
            assertEquals(CurrencyCode.JPY, model.state.value.addDraft.homeCurrency)
            assertEquals("1200", model.state.value.addDraft.amountYuanInput)
            assertEquals(1200L, model.state.value.addDraft.parsedAmountCents())
            model.resetDraft()
            assertEquals(CurrencyCode.CNY, model.state.value.addDraft.homeCurrency)
            assertEquals("", model.state.value.addDraft.amountYuanInput)
        } finally {
            Dispatchers.resetMain()
        }
    }
}
