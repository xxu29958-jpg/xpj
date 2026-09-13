package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.BudgetAdviceInputsDto
import com.ticketbox.data.remote.dto.DiscretionaryResponseDto
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class BudgetAdviceFxRecoveryTest {
    private val gap = MissingExchangeRateDto("JPY", "CNY", "2026-09-01")
    private fun missingInputs() = BudgetAdviceInputsDto("2026-09", "CNY",
        DiscretionaryResponseDto(10000, 1000, null, 0, 0, null), listOf(gap))

    @Test fun queuedGenerationCannotReopenLoadingAfterBindingReplacement() = budgetTest {
        val binding = LogicalSessionBinding("https://example.test", "owner", "identity", "session", "revision")
        val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(binding, true))
        val fake = FakeBudgetActions(budget(), activeAccessFlow = access)
        val vm = BudgetAdviceViewModel(fake, initialMonth = "2026-09")
        advanceUntilIdle()
        access.value = LedgerAccessContext(binding.copy(bindingRevision = "replacement"), true)
        vm.requestAdvice()
        advanceUntilIdle()
        assertTrue(fake.adviceMonths.isEmpty())
        assertEquals(BudgetAdviceLoadState.Idle, vm.uiState.value.loadState)
        assertEquals("replacement", vm.uiState.value.binding?.bindingRevision)
    }

    @Test fun missingRatesAndRateSubmissionOnlyReadTheOriginalMonthWithoutCallingAdvisor() = budgetTest {
        val fake = FakeBudgetActions(budget()).apply { inputResponse = missingInputs() }
        val vm = BudgetAdviceViewModel(fake, initialMonth = "2026-09")
        advanceUntilIdle()
        vm.requestAdvice()
        vm.openRate(gap)
        advanceUntilIdle()
        vm.updateRateInput("0.05")
        vm.saveRate()
        advanceUntilIdle()
        assertEquals(listOf("2026-09"), fake.rates.writes.map { it.first })
        assertEquals("JPY", fake.rates.writes.single().second.currencyCode)
        assertEquals("2026-09-01", fake.rates.writes.single().second.rateDate)
        assertTrue(fake.adviceMonths.isEmpty())
        fake.inputResponse = missingInputs().copy(breakdown = DiscretionaryResponseDto(10000, 1000, 2000, 0, 0, 7000), missingRates = emptyList())
        vm.refreshInputs()
        advanceUntilIdle()
        assertTrue(fake.inputMonths.all { it == "2026-09" })
        assertTrue(fake.adviceMonths.isEmpty())
        vm.requestAdvice()
        advanceUntilIdle()
        assertEquals(listOf("2026-09"), fake.adviceMonths)
    }

    @Test fun unknownSourceOrDateCannotInventAManualRateIdentity() = budgetTest {
        val fake = FakeBudgetActions(budget()).apply { inputResponse = missingInputs() }
        val vm = BudgetAdviceViewModel(fake, initialMonth = "2026-09")
        advanceUntilIdle()
        vm.openRate(gap.copy(sourceCurrencyCode = null))
        vm.openRate(gap.copy(rateDate = null))
        advanceUntilIdle()
        assertNull(vm.uiState.value.rateEditor)
        assertTrue(fake.rates.writes.isEmpty())
    }

    @Test fun bindingReplacementClearsRateEditorAndPreventsOriginalSave() = budgetTest {
        val binding = LogicalSessionBinding("https://example.test", "owner", "identity", "session", "revision")
        val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(binding, true))
        val fake = FakeBudgetActions(budget(), activeAccessFlow = access).apply { inputResponse = missingInputs() }
        val vm = BudgetAdviceViewModel(fake, initialMonth = "2026-09")
        advanceUntilIdle()
        vm.openRate(gap)
        advanceUntilIdle()
        vm.updateRateInput("0.05")
        access.value = LedgerAccessContext(binding.copy(bindingRevision = "replacement"), true)
        advanceUntilIdle()
        vm.saveRate()
        advanceUntilIdle()
        assertNull(vm.uiState.value.rateEditor)
        assertTrue(fake.rates.writes.isEmpty())
    }
}
