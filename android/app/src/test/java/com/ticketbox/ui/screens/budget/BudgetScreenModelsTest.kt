package com.ticketbox.ui.screens.budget

import com.ticketbox.R
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.BudgetUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class BudgetScreenModelsTest {
    @Test
    fun decisionKeepsExecutionSectionsHiddenWhenBudgetIsNotEnabled() {
        val decision = budgetPageDecision(
            BudgetUiState(budget = budget(configured = false)),
        )

        assertEquals(BudgetPageStatus.NotEnabled, decision.status)
        assertNull(decision.configuredBudget)
    }

    @Test
    fun decisionShowsExecutionSectionsOnlyForConfiguredBudget() {
        val decision = budgetPageDecision(
            BudgetUiState(budget = budget(configured = true)),
        )

        assertEquals(BudgetPageStatus.Active, decision.status)
        assertNotNull(decision.configuredBudget)
    }

    @Test
    fun decisionSeparatesInitialLoadingFromLoadFailure() {
        val loading = budgetPageDecision(BudgetUiState(loading = true))
        val failed = budgetPageDecision(
            BudgetUiState(loadError = UiText.res(R.string.budget_message_load_failed)),
        )

        assertEquals(BudgetPageStatus.Loading, loading.status)
        assertEquals(BudgetPageStatus.LoadFailed, failed.status)
    }

    private fun budget(configured: Boolean): BudgetMonthly = BudgetMonthly(
        ledgerId = "ledger-1",
        month = "2026-07",
        configured = configured,
        totalAmountCents = if (configured) 300000 else 0,
        rolloverAmountCents = 0,
        fixedAmountCents = 0,
        nonMonthlyAmountCents = 0,
        flexBudgetCents = 300000,
        spentAmountCents = 120000,
        excludedAmountCents = 0,
        remainingAmountCents = 180000,
        overspentAmountCents = 0,
        excludedCategories = emptyList(),
        excludedBreakdown = emptyList(),
        categoryBudgets = emptyList(),
        updatedAt = "2026-07-01T00:00:00Z",
        rowVersion = 1,
    )
}
