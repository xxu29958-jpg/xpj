package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.BudgetProgressStatus
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

/** Read refusal retires displayed financial data; it does not rewrite the user's draft. */
@OptIn(ExperimentalCoroutinesApi::class)
class BudgetReadAccessTest {
    @Test fun permissionRefusalHidesBudgetButKeepsTheOriginalDraftAndOcc() = budgetTest {
        val repository = FakeBudgetActions(budget(month = "2026-09"))
        val model = BudgetViewModel(repository, initialMonth = "2026-09")
        advanceUntilIdle()
        assertNotNull(model.uiState.value.budget)
        assertEquals(repository.readFetchedAt, model.uiState.value.fetchedAt)
        model.updateTotalAmount("1250.25")
        val original = model.uiState.value.form
        repository.monthlyBudgetResponder = { Result.failure(refused()) }

        model.refresh()
        advanceUntilIdle()

        assertNull(model.uiState.value.budget, "An explicit refusal is not permission to keep showing the last read")
        assertNull(model.uiState.value.fetchedAt)
        assertEquals(false, model.uiState.value.fromCache)
        assertNotNull(model.uiState.value.loadError)
        assertEquals(original, model.uiState.value.form)
        assertEquals(true, model.uiState.value.formDirty)
        assertEquals("2026-09", model.uiState.value.month)
    }

    @Test fun permissionRefusalAlsoRetiresTheInsightsBudgetCard() = budgetTest {
        val repository = FakeBudgetActions(budget(month = "2026-09"))
        val model = StatsBudgetViewModel(repository)
        advanceUntilIdle()
        model.refresh("2026-09")
        advanceUntilIdle()
        assertNotNull(model.uiState.value.budgetProgress)
        assertEquals(repository.readFetchedAt, model.uiState.value.fetchedAt)
        repository.monthlyBudgetResponder = { Result.failure(refused()) }

        model.refresh("2026-09", force = true)
        advanceUntilIdle()

        assertNull(model.uiState.value.budgetProgress)
        assertNull(model.uiState.value.fetchedAt)
        assertEquals(false, model.uiState.value.fromCache)
        assertEquals(BudgetProgressStatus.Unknown, model.uiState.value.budgetProgressStatus)
        assertEquals("2026-09", model.uiState.value.month)
    }

    @Test fun offlineBudgetAndInsightsRetainTheOriginalReadTimeAndOnlyPublishItForTheSameBindingAndMonth() = budgetTest {
        val repository = FakeBudgetActions(budget(month = "2026-09"))
        repository.readFromCache = true
        val model = BudgetViewModel(repository, initialMonth = "2026-09")
        val insights = StatsBudgetViewModel(repository)
        advanceUntilIdle()
        insights.refresh("2026-09")
        advanceUntilIdle()
        assertEquals(repository.readFetchedAt, model.uiState.value.fetchedAt)
        assertEquals(true, model.uiState.value.fromCache)
        val read = insights.uiState.value
        val matching = MonthlyStatsUiState(binding = read.binding, month = read.month)
        val shown = mergeStatsUiState(matching, read, StatsReportsUiState())
        assertEquals(model.uiState.value.budget?.remainingAmountCents, shown.budgetProgress?.remainingCents)
        assertEquals(repository.readFetchedAt, shown.budgetFetchedAt)
        assertEquals(true, shown.budgetFromCache)
        for (other in listOf(matching.copy(month = "2026-10"), matching.copy(binding = null))) {
            val hidden = mergeStatsUiState(other, read, StatsReportsUiState())
            assertNull(hidden.budgetProgress)
            assertNull(hidden.budgetFetchedAt)
            assertEquals(false, hidden.budgetFromCache)
        }
    }

    @Test fun permissionRefusalClearsTheUntouchedQueryFormAndCannotSubmitItsAmounts() = budgetTest {
        val queried = budget(month = "2026-09").copy(homeCurrencyCode = "JPY", rolloverAmountCents = 300,
            nonMonthlyAmountCents = 400, excludedCategories = listOf("医疗"), categoryBudgets = listOf(
                com.ticketbox.domain.model.BudgetCategoryBudget("餐饮", 500, null, null, null)))
        val repository = FakeBudgetActions(queried)
        val model = BudgetViewModel(repository, initialMonth = "2026-09")
        advanceUntilIdle()
        assertEquals(BudgetFormState(totalAmount = "300000", rolloverAmount = "300", nonMonthlyAmount = "400",
            excludedCategories = "医疗", categoryRows = listOf(BudgetCategoryInput("餐饮", "500")),
            homeCurrencyCode = "JPY", expectedRowVersion = 1), model.uiState.value.form)
        assertEquals(false, model.uiState.value.formDirty)
        val originals = repository.commands.saves.value
        repository.monthlyBudgetResponder = { Result.failure(refused()) }

        model.refresh()
        advanceUntilIdle()
        model.save()
        advanceUntilIdle()

        assertNull(model.uiState.value.budget)
        assertNull(model.uiState.value.fetchedAt)
        assertEquals(BudgetFormState(), model.uiState.value.form,
            "An untouched form is another copy of the refused query, including currency, categories and OCC")
        assertEquals(false, model.uiState.value.formDirty)
        assertEquals(0, repository.commands.savedRequests.size,
            "A refused server-derived form must not remain a valid new save command")
        assertEquals(originals, repository.commands.saves.value)
    }

    private fun refused() = RepositoryException("Synthetic read refusal", errorCode = "permission_denied", httpStatusCode = 403)
}
